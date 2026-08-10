"""Flagship signature analyses over CI/CD telemetry (pure analysis).

These are the differentiators — transparent heuristics, every flag reported with
its numbers so an operator can see *why* something was ranked, never a black-box
verdict:

  1. ``pipeline_failure_rca`` — classify recent failed pipelines from job
     status + trace tail (test failure vs dependency/network vs runner timeout
     vs OOM vs script error) and attach a cause + action per pipeline.
  2. ``runner_health_rca`` — offline/stale runners, jobs queued longer than a
     threshold, and runner saturation by tag.
  3. ``artifact_storage_bloat_analysis`` — projects ranked by artifacts + repo
     size, expired-but-kept artifacts, and a reclaimable-bytes estimate.
  4. ``stale_work_audit`` — long-open merge/pull requests, branches with no
     activity for N days, and protected-branch configuration gaps.

All four are pure functions (no I/O): pass them the telemetry (from the reads
in the other ops modules, or injected) and they return the analysis. The live
pulls that feed them live in the ``pull_*`` helpers of the read modules and in
:func:`pull_failed_pipelines` here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cicd_aiops.ops import pipelines as pipe_ops
from cicd_aiops.ops._util import age_days, age_seconds, num, opt, s


class PipelineProbeFailed(RuntimeError):  # noqa: N818 — reads as a statement, like UnsupportedResource
    """The failed-pipeline listing could not be read at all.

    Distinct from "there are no failed pipelines": a probe that never ran must
    not be summarised as a healthy zero. Raised by ``pull_failed_pipelines`` so
    the RCA reports the reason (a 404, an auth error, or a platform that has no
    pipeline-run resource) rather than an empty, confident result.
    """

MAX_ROWS = 100


def _cut(rows: list, limit: int = MAX_ROWS) -> tuple[list, bool]:
    """Cap a findings list at ``limit``, MEASURING whether anything was dropped.

    Analyses cap their findings so a result stays readable. That cap used to be
    silent: a model reading 100 findings could not tell whether it had all of
    them. ``_cut`` returns the flag alongside the rows, and every analysis
    reports it under ``truncated``.
    """
    return rows[:limit], len(rows) > limit

# ── 1. pipeline-failure RCA ──────────────────────────────────────────────────
DEFAULT_FAILED_PIPELINES = 10

# Trace-tail signatures, checked in order of specificity (OOM before generic
# "killed"; network before generic test words). Every tuple: (marker, class).
_OOM_MARKERS = (
    "out of memory", "oom-kill", "oomkilled", "cannot allocate memory",
    "exit code 137", "signal 9", "java.lang.outofmemoryerror",
)
_TIMEOUT_MARKERS = (
    "execution took longer than", "job exceeded maximum timeout",
    "timeout exceeded", "deadline exceeded", "timed out",
)
_NETWORK_MARKERS = (
    "could not resolve host", "temporary failure in name resolution",
    "connection refused", "connection timed out", "network is unreachable",
    "connection reset by peer", "econnreset", "etimedout",
    "failed to fetch", "npm err! network", "max retries exceeded",
    "could not connect to", "tls handshake", "proxy error", "502 bad gateway",
)
_TEST_MARKERS = (
    "assertionerror", "assertion failed", "tests failed", "test failed",
    "failures:", "failed=", "expected ", "1 failing", "failing tests",
    "pytest", "go test", "junit",
)
_SCRIPT_MARKERS = (
    "command not found", "syntax error", "no such file or directory",
    "permission denied", "exit status 1", "exit code 1",
)

# GitLab failure_reason values that classify without a trace.
_REASON_CLASSES = {
    "stuck_or_timeout_failure": "runner-timeout",
    "runner_system_failure": "runner-timeout",
    "scheduler_failure": "runner-timeout",
    "api_failure": "dependency-network",
    "missing_dependency_failure": "dependency-network",
    "script_failure": "",  # needs the trace to say more
}

_CLASS_ACTIONS = {
    "test-failure": (
        "Test failure — assertions failed in the test stage",
        "Read the failing test names in the trace and fix the regression; "
        "rerun only after the test passes locally.",
    ),
    "dependency-network": (
        "Dependency/network failure — a fetch, resolve or connect failed",
        "Check registry/mirror reachability from the runner and retry the "
        "pipeline; pin or cache flaky dependencies.",
    ),
    "runner-timeout": (
        "Runner timeout / infrastructure failure — the job never finished",
        "Raise the job timeout or move the job to a less loaded runner tag; "
        "check the runner host's load.",
    ),
    "oom": (
        "Out-of-memory — the job was killed for exceeding memory",
        "Raise the job/runner memory limit or shrink the build's working set "
        "(split the job, reduce parallelism).",
    ),
    "script-error": (
        "Script error — the job script itself failed",
        "Inspect the trace tail: fix the failing command, missing file, or "
        "permissions in the job definition.",
    ),
}


def classify_job_failure(job: dict) -> dict:
    """Classify one failed job from its failure_reason + trace tail.

    Returns {class, cause, action, evidence} where evidence is the matched
    marker (or the failure_reason) so the classification is auditable.
    """
    reason = str(job.get("failureReason") or "").lower()
    mapped = _REASON_CLASSES.get(reason, "")
    trace = str(job.get("traceTail") or "").lower()

    checks = (
        ("oom", _OOM_MARKERS),
        ("runner-timeout", _TIMEOUT_MARKERS),
        ("dependency-network", _NETWORK_MARKERS),
        ("test-failure", _TEST_MARKERS),
        ("script-error", _SCRIPT_MARKERS),
    )
    found_class, evidence = "", ""
    for cls, markers in checks:
        for marker in markers:
            if marker in trace:
                found_class, evidence = cls, marker
                break
        if found_class:
            break

    if not found_class:
        if mapped:
            found_class, evidence = mapped, f"failure_reason={reason}"
        elif "test" in str(job.get("stage") or "").lower() or "test" in str(
            job.get("name") or ""
        ).lower():
            found_class, evidence = "test-failure", "job/stage name contains 'test'"
        else:
            found_class, evidence = "script-error", "no marker matched (fallback)"

    cause, action = _CLASS_ACTIONS[found_class]
    return {"class": found_class, "cause": cause, "action": action, "evidence": s(evidence, 120)}


def pull_failed_pipelines(
    conn: Any,
    project: str,
    limit: int = DEFAULT_FAILED_PIPELINES,
    tail_lines: int = pipe_ops.DEFAULT_TRACE_TAIL_LINES,
) -> list[dict]:
    """[READ] Live failed pipelines with their failed jobs + trace tails.

    Each failed job carries ``traceTruncated`` — the trace is only the tail, so
    the first error may have scrolled off. A classification drawn from a
    truncated tail is a hypothesis, not a verdict.
    """
    listed = pipe_ops.list_pipelines(conn, project, status="failed", limit=limit)
    # "Could not look" must never render as "nothing is failing". list_pipelines
    # reports a failed probe as an {"error": ...} envelope, and reading
    # .get("pipelines", []) off it produced a clean, confident zero — measured
    # on a real Gitea, where the run listing 404'd while the server held a
    # genuinely failed job. Re-raise so the RCA reports the probe failure.
    if isinstance(listed, dict) and listed.get("error"):
        raise PipelineProbeFailed(str(listed["error"]))
    out: list[dict] = []
    for p in listed.get("pipelines", []) if isinstance(listed, dict) else []:
        jobs = pipe_ops.pipeline_jobs(conn, project, p["id"])
        failed_jobs = []
        for j in jobs.get("jobs", []) if isinstance(jobs, dict) else []:
            if j.get("status") not in ("failed", "failure"):
                continue
            trace = pipe_ops.job_trace_tail(conn, project, j["id"], tail_lines=tail_lines)
            j = dict(j)
            j["traceTail"] = trace.get("trace", "") if isinstance(trace, dict) else ""
            # The trace is a tail: earlier lines may hold the real first error.
            j["traceTruncated"] = bool(
                isinstance(trace, dict)
                and (trace.get("truncated") or trace.get("charsTruncated"))
            )
            failed_jobs.append(j)
        entry = dict(p)
        entry["jobs"] = failed_jobs
        out.append(entry)
    return out


def pipeline_failure_rca(failed_pipelines: list[dict]) -> dict:
    """[READ] Classify failed pipelines: cause + action per pipeline.

    Pure analysis over ``failed_pipelines`` rows (from
    ``pull_failed_pipelines`` or injected): {id, ref, status,
    jobs:[{name, stage, status, failureReason, traceTail}]}. Each failed job is
    classified (test-failure / dependency-network / runner-timeout / oom /
    script-error) from its failure_reason and trace-tail markers; the
    pipeline's headline class is its first failed job's. Every classification
    carries its matched evidence.
    """
    results = []
    class_counts: dict[str, int] = {}
    for p in failed_pipelines or []:
        job_findings = []
        for job in p.get("jobs", []) or []:
            if str(job.get("status", "")).lower() not in ("failed", "failure"):
                continue
            finding = {
                "job": s(job.get("name")),
                "stage": opt(job.get("stage")),
            }
            finding.update(classify_job_failure(job))
            job_findings.append(finding)
            class_counts[finding["class"]] = class_counts.get(finding["class"], 0) + 1
        jobs_shown, jobs_truncated = _cut(job_findings)
        results.append(
            {
                "pipeline": s(p.get("id")),
                "ref": s(p.get("ref")),
                "headlineClass": job_findings[0]["class"] if job_findings else "unknown",
                "cause": job_findings[0]["cause"] if job_findings else
                "No failed job rows available for this pipeline",
                "action": job_findings[0]["action"] if job_findings else
                "Pull the pipeline's jobs and traces, then re-run the RCA.",
                "failedJobs": jobs_shown,
                "failedJobsTruncated": jobs_truncated,
            }
        )

    shown, truncated = _cut(results)
    return {
        "pipelinesEvaluated": len(results),
        "classCounts": class_counts,
        "pipelines": shown,
        "returned": len(shown),
        "limit": MAX_ROWS,
        "truncated": truncated,
        "note": (
            "Advisory read-only heuristic: failed jobs are classified by "
            "failure_reason and trace-tail markers (OOM > timeout > network > "
            "test > script, most-specific first); every finding names its "
            "matched evidence."
        ),
    }


# ── 2. runner health & queue RCA ─────────────────────────────────────────────
DEFAULT_STALE_CONTACT_MIN = 30.0
DEFAULT_QUEUE_SEC = 300.0
DEFAULT_SATURATION_RATIO = 2.0


def runner_health_rca(
    runners: list[dict],
    queued_jobs: list[dict] | None = None,
    stale_contact_min: float = DEFAULT_STALE_CONTACT_MIN,
    queue_sec: float = DEFAULT_QUEUE_SEC,
    saturation_ratio: float = DEFAULT_SATURATION_RATIO,
    now: datetime | None = None,
) -> dict:
    """[READ] Flag offline/stale/paused runners, long-queued jobs, tag saturation.

    Pure analysis over ``runners`` rows (from ``pull_runners`` or injected):
    {id, description, status, paused, online, tags, contactedAt} and optional
    ``queued_jobs`` rows {id, name, status, queuedDurationSec, createdAt,
    tags}. A runner is *offline* when status/online says so, *stale* when its
    last contact is older than ``stale_contact_min`` minutes. A queued job is
    flagged when it has waited longer than ``queue_sec``. A tag is *saturated*
    when flagged queued jobs per online runner exceed ``saturation_ratio``.
    """
    flagged_runners = []
    online_by_tag: dict[str, int] = {}
    for r in runners or []:
        online = bool(r.get("online")) and str(r.get("status", "")).lower() != "offline"
        contact_age_min = age_days(r.get("contactedAt"), now)
        contact_age_min = None if contact_age_min is None else contact_age_min * 1440.0
        stale = online and contact_age_min is not None and contact_age_min >= stale_contact_min
        paused = bool(r.get("paused"))
        for tag in r.get("tags") or []:
            if online and not paused:
                online_by_tag[tag] = online_by_tag.get(tag, 0) + 1
        if online and not stale and not paused:
            continue
        if not online:
            cause = "Runner is offline (not contacting the server)"
            action = (
                "Check the runner host/service and its registration token; "
                "restart the runner service."
            )
        elif stale:
            cause = (
                f"Runner is stale — last contact {contact_age_min:.0f} min ago "
                f"(threshold {stale_contact_min:.0f})"
            )
            action = "Check the runner host's clock/network; restart if wedged."
        else:
            cause = "Runner is paused — it will not pick up jobs"
            action = "Resume it (resume_runner) if the pause is no longer needed."
        flagged_runners.append(
            {
                "id": s(r.get("id")),
                "description": opt(r.get("description")),
                "status": s(r.get("status")),
                "online": online,
                "paused": paused,
                "lastContactMin": round(contact_age_min, 1) if contact_age_min else None,
                "tags": [s(t, 64) for t in (r.get("tags") or [])],
                "cause": cause,
                "action": action,
            }
        )

    long_queued = []
    queued_by_tag: dict[str, int] = {}
    for j in queued_jobs or []:
        waited = j.get("queuedDurationSec")
        waited = num(waited) if waited is not None else (age_seconds(j.get("createdAt"), now) or 0)
        if waited < queue_sec:
            continue
        tags = [s(t, 64) for t in (j.get("tags") or [])]
        for tag in tags:
            queued_by_tag[tag] = queued_by_tag.get(tag, 0) + 1
        long_queued.append(
            {
                "job": s(j.get("id")),
                "name": s(j.get("name")),
                "queuedSec": round(waited, 0),
                "tags": tags,
                "cause": (
                    f"Queued {waited:.0f}s (threshold {queue_sec:.0f}s) — "
                    f"no runner picked it up"
                ),
                "action": "Check the tag's runner capacity below; add or resume runners for it.",
            }
        )

    saturated_tags = []
    for tag, queued in queued_by_tag.items():
        online = online_by_tag.get(tag, 0)
        ratio = queued / online if online else float("inf")
        if ratio >= saturation_ratio:
            saturated_tags.append(
                {
                    "tag": tag,
                    "queuedJobs": queued,
                    "onlineRunners": online,
                    "ratio": None if online == 0 else round(ratio, 2),
                    "cause": (
                        f"Tag '{tag}' saturated: {queued} long-queued job(s) vs "
                        f"{online} online unpaused runner(s)"
                    ),
                    "action": "Add runners with this tag or widen the jobs' tag list.",
                }
            )
    saturated_tags.sort(key=lambda t: t["queuedJobs"], reverse=True)

    flagged_shown, flagged_cut = _cut(flagged_runners)
    queued_shown, queued_cut = _cut(long_queued)
    tags_shown, tags_cut = _cut(saturated_tags)
    return {
        "runnersEvaluated": len(runners or []),
        "flaggedRunners": flagged_shown,
        "longQueuedJobs": queued_shown,
        "saturatedTags": tags_shown,
        "limit": MAX_ROWS,
        "truncated": {
            "flaggedRunners": flagged_cut,
            "longQueuedJobs": queued_cut,
            "saturatedTags": tags_cut,
        },
        "thresholds": {
            "staleContactMin": stale_contact_min,
            "queueSec": queue_sec,
            "saturationRatio": saturation_ratio,
        },
        "note": (
            "Advisory read-only heuristic: offline/stale/paused runners flagged; "
            "jobs queued past queueSec listed; a tag is saturated when flagged "
            "queued jobs per online unpaused runner >= saturationRatio."
        ),
    }


# ── 3. artifact/storage bloat analysis ───────────────────────────────────────
DEFAULT_OLD_ARTIFACT_DAYS = 30.0


def artifact_storage_bloat_analysis(
    projects: list[dict],
    artifacts_by_project: dict[str, list[dict]] | None = None,
    old_artifact_days: float = DEFAULT_OLD_ARTIFACT_DAYS,
    now: datetime | None = None,
) -> dict:
    """[READ] Rank projects by storage and estimate reclaimable artifact bytes.

    Pure analysis over ``projects`` rows (from ``pull_projects_with_stats`` or
    injected): {path, repoBytes, artifactsBytes, storageBytes} and optional
    ``artifacts_by_project`` — {project: [{file, sizeBytes, createdAt,
    expireAt}]}. Reclaimable = expired-but-kept artifact bytes + artifacts
    older than ``old_artifact_days``. Every ranking carries its byte numbers.
    """
    ranked = []
    total_reclaimable = 0.0
    art_bytes_unknown = 0
    for p in projects or []:
        path = s(p.get("path"))
        repo_b = num(p.get("repoBytes"))
        art_known = p.get("artifactsBytes") is not None
        art_bytes_unknown += 0 if art_known else 1
        art_b = num(p.get("artifactsBytes"))
        rows = (artifacts_by_project or {}).get(path, [])
        expired_b = old_b = 0.0
        expired_n = old_n = 0
        for a in rows:
            size = num(a.get("sizeBytes"))
            expire_age = age_days(a.get("expireAt"), now)
            created_age = age_days(a.get("createdAt"), now)
            if a.get("expireAt") and expire_age is not None and expire_age > 0:
                expired_b += size
                expired_n += 1
            elif created_age is not None and created_age >= old_artifact_days:
                old_b += size
                old_n += 1
        reclaimable = expired_b + old_b
        total_reclaimable += reclaimable
        ranked.append(
            {
                "project": path,
                "repoBytes": repo_b,
                "artifactsBytes": art_b if art_known else None,
                "artifactsBytesKnown": art_known,
                "totalBytes": repo_b + art_b,
                "expiredButKept": expired_n,
                "expiredBytes": expired_b,
                "olderThanDays": old_n,
                "oldBytes": old_b,
                "reclaimableBytes": reclaimable,
                "action": (
                    "Run delete_artifacts (dry_run first) to reclaim expired/old "
                    "artifact bytes."
                    if reclaimable > 0
                    else "No obvious artifact reclaim for this project."
                ),
            }
        )
    ranked.sort(key=lambda e: e["totalBytes"], reverse=True)

    shown, truncated = _cut(ranked)
    return {
        "projectsEvaluated": len(ranked),
        "totalReclaimableBytes": total_reclaimable,
        "artifactBytesUnavailable": art_bytes_unknown,
        "thresholds": {"oldArtifactDays": old_artifact_days},
        "projects": shown,
        "returned": len(shown),
        "limit": MAX_ROWS,
        "truncated": truncated,
        "note": (
            "Advisory read-only heuristic: projects ranked by repo + artifact "
            "bytes; reclaimable = expired-but-kept artifacts plus artifacts "
            "older than oldArtifactDays. Verify before deleting — sizes come "
            "from the server's own statistics. 'artifactsBytesKnown': false "
            "(counted in artifactBytesUnavailable) means the platform does not "
            "report artifact storage for that project — it is unmeasured, NOT "
            "zero, and such a project is ranked on repo bytes alone."
        ),
    }


# ── 4. stale-work audit ──────────────────────────────────────────────────────
DEFAULT_STALE_MR_DAYS = 14.0
DEFAULT_STALE_BRANCH_DAYS = 90.0


def stale_work_audit(
    merge_requests: list[dict],
    branches: list[dict],
    protections: list[dict] | None = None,
    default_branch: str = "",
    stale_mr_days: float = DEFAULT_STALE_MR_DAYS,
    stale_branch_days: float = DEFAULT_STALE_BRANCH_DAYS,
    now: datetime | None = None,
) -> dict:
    """[READ] Long-open MRs/PRs, inactive branches, protection config gaps.

    Pure analysis over merge-request rows {id, title, state, updatedAt,
    draft}, branch rows {name, default, protected, lastCommitAt} and optional
    protection rows {branch, allowForcePush}. Flags: open MRs not updated for
    ``stale_mr_days``; branches with no commit for ``stale_branch_days``; a
    default branch that is unprotected; protection rules that allow force-push.
    """
    stale_mrs = []
    for mr in merge_requests or []:
        if str(mr.get("state", "")).lower() not in ("opened", "open"):
            continue
        idle = age_days(mr.get("updatedAt") or mr.get("createdAt"), now)
        if idle is None or idle < stale_mr_days:
            continue
        stale_mrs.append(
            {
                "id": s(mr.get("id")),
                "title": s(mr.get("title"), 120),
                "idleDays": round(idle, 1),
                "draft": bool(mr.get("draft")),
                "cause": f"Open for review with no update for {idle:.0f} days "
                f"(threshold {stale_mr_days:.0f})",
                "action": "Ping the author/reviewer to merge or close it.",
            }
        )
    stale_mrs.sort(key=lambda m: m["idleDays"], reverse=True)

    stale_branches = []
    protected_names = {s(p.get("branch")) for p in protections or []}
    for b in branches or []:
        if b.get("default"):
            continue
        idle = age_days(b.get("lastCommitAt"), now)
        if idle is None or idle < stale_branch_days:
            continue
        stale_branches.append(
            {
                "name": s(b.get("name")),
                "idleDays": round(idle, 1),
                "protected": bool(b.get("protected")),
                "cause": f"No commit for {idle:.0f} days (threshold {stale_branch_days:.0f})",
                "action": "Delete the branch if its work is merged or abandoned.",
            }
        )
    stale_branches.sort(key=lambda b: b["idleDays"], reverse=True)

    gaps = []
    if default_branch:
        default_protected = any(
            b.get("default") and b.get("protected") for b in branches or []
        ) or s(default_branch) in protected_names
        if not default_protected:
            gaps.append(
                {
                    "branch": s(default_branch),
                    "gap": "default-branch-unprotected",
                    "cause": "The default branch has no protection rule",
                    "action": "Protect it (update_branch_protection) so history "
                    "cannot be rewritten or force-pushed.",
                }
            )
    for p in protections or []:
        if p.get("allowForcePush"):
            gaps.append(
                {
                    "branch": s(p.get("branch")),
                    "gap": "force-push-allowed",
                    "cause": "The protection rule allows force-push",
                    "action": "Disable force-push (update_branch_protection) unless "
                    "this branch explicitly needs history rewrites.",
                }
            )

    mrs_shown, mrs_cut = _cut(stale_mrs)
    branches_shown, branches_cut = _cut(stale_branches)
    gaps_shown, gaps_cut = _cut(gaps)
    return {
        "staleMergeRequests": mrs_shown,
        "staleBranches": branches_shown,
        "protectionGaps": gaps_shown,
        "limit": MAX_ROWS,
        "truncated": {
            "staleMergeRequests": mrs_cut,
            "staleBranches": branches_cut,
            "protectionGaps": gaps_cut,
        },
        "counts": {
            "staleMergeRequests": len(stale_mrs),
            "staleBranches": len(stale_branches),
            "protectionGaps": len(gaps),
        },
        "thresholds": {
            "staleMrDays": stale_mr_days,
            "staleBranchDays": stale_branch_days,
        },
        "note": (
            "Advisory read-only heuristic: open MRs idle past staleMrDays, "
            "non-default branches idle past staleBranchDays, default-branch "
            "protection and force-push settings checked. Review before deleting "
            "anything."
        ),
    }

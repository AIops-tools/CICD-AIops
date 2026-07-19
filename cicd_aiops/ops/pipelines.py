"""Pipeline reads — list, detail, jobs, trace tail (read-only).

Platform-neutral pipeline surface: GitLab pipelines (``/pipelines``) and Gitea
Actions runs (``/actions/runs``) return the same concepts under different field
names, reconciled through the shared field pickers. Nothing here mutates a
pipeline — retry/cancel live in :mod:`cicd_aiops.ops.writes`.

Every listing here returns a truncation envelope (``returned`` / ``limit`` /
``truncated``) rather than a bare list. Pipeline and job feeds are long, and a
silently-cut list is exactly where a smaller model reports "no data returned"
or treats a partial page as the whole story.
"""

from __future__ import annotations

from typing import Any

from cicd_aiops.ops._util import as_obj, listing, opt, page_limit, pick, s

_MAX_LIST = 100
DEFAULT_TRACE_TAIL_LINES = 60
_MAX_TRACE_CHARS = 8000


def norm_pipeline(r: dict) -> dict:
    """Normalise one pipeline/run row across GitLab / Gitea field names.

    Fields the server may simply not report (``ref``, ``sha``, ``source``,
    timestamps, ``webUrl``) stay ``None`` rather than collapsing to ``""``.
    """
    return {
        "id": s(pick(r, "id")),
        "status": s(pick(r, "status", "conclusion"), 32).lower(),
        "ref": opt(pick(r, "ref", "head_branch")),
        "sha": opt(pick(r, "sha", "head_sha"), 64),
        "source": opt(pick(r, "source", "event", "trigger_event")),
        "createdAt": opt(pick(r, "created_at")),
        "updatedAt": opt(pick(r, "updated_at")),
        "durationSec": pick(r, "duration", default=None),
        "webUrl": opt(pick(r, "web_url", "url", "html_url")),
    }


def norm_job(r: dict) -> dict:
    """Normalise one job row across GitLab / Gitea field names.

    A job that never started has no ``startedAt``; a job that succeeded has no
    ``failureReason``; a job the server did not attribute to a runner has no
    ``runner``. All three come back as ``None``, not ``""``.
    """
    return {
        "id": s(pick(r, "id")),
        "name": s(pick(r, "name")),
        "stage": opt(pick(r, "stage")),
        "status": s(pick(r, "status", "conclusion"), 32).lower(),
        "failureReason": opt(pick(r, "failure_reason")),
        "createdAt": opt(pick(r, "created_at")),
        "startedAt": opt(pick(r, "started_at")),
        "finishedAt": opt(pick(r, "finished_at", "completed_at")),
        "durationSec": pick(r, "duration", default=None),
        "runner": opt(pick(as_obj(r.get("runner")), "description", "name")),
        "tags": [s(t, 64) for t in (r.get("tag_list") or []) if isinstance(t, str)],
        "queuedDurationSec": pick(r, "queued_duration", default=None),
    }


def list_pipelines(
    conn: Any, project: str, status: str | None = None, limit: int = 20
) -> dict:
    """[READ] Recent pipelines/runs for a project, newest first.

    Returns ``{project, pipelines, returned, limit, truncated}``. One row beyond
    ``limit`` is requested, so ``truncated`` is measured — it says "the server
    had more", never "the page happened to be full".
    """
    try:
        requested, per_page = page_limit(limit, _MAX_LIST)
        params: dict[str, Any] = {"per_page": per_page}
        if status:
            params["status"] = s(status, 32).lower()
        rows = conn.platform.rows(
            conn.get(conn.platform.path("pipelines", project=project), params=params)
        )
        truncated = len(rows) > requested
        pipelines = [norm_pipeline(r) for r in rows[:requested]]
        return listing("pipelines", pipelines, requested, truncated, project=s(project))
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "project": s(project)}


def pipeline_detail(conn: Any, project: str, pipeline: str) -> dict:
    """[READ] One pipeline/run's full detail."""
    try:
        raw = conn.get(conn.platform.path("pipeline", project=project, pipeline=pipeline))
        detail = norm_pipeline(as_obj(conn.platform.normalise(raw)))
        detail["project"] = s(project)
        return detail
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "project": s(project), "pipeline": s(pipeline)}


def pipeline_jobs(
    conn: Any, project: str, pipeline: str, limit: int = _MAX_LIST
) -> dict:
    """[READ] Jobs of one pipeline/run with status + failure reason.

    The jobs endpoint returns the whole set for a pipeline, so truncation is
    measured against the full fetched list rather than by over-fetching.
    """
    try:
        rows = conn.platform.rows(
            conn.get(conn.platform.path("pipeline_jobs", project=project, pipeline=pipeline))
        )
        requested = max(1, int(limit))
        truncated = len(rows) > requested
        jobs = [norm_job(r) for r in rows[:requested]]
        return listing(
            "jobs", jobs, requested, truncated, project=s(project), pipeline=s(pipeline)
        )
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "project": s(project), "pipeline": s(pipeline)}


def job_trace_tail(
    conn: Any, project: str, job: str, tail_lines: int = DEFAULT_TRACE_TAIL_LINES
) -> dict:
    """[READ] The tail of one job's log/trace (the part that explains failures).

    A trace is truncated twice — to the last ``tail_lines`` lines, and again to
    a byte ceiling — and both cuts are reported: ``truncated`` when earlier
    lines were dropped, ``charsTruncated`` when the tail itself was clipped.
    A log read that silently loses its head is the classic case where a model
    concludes the wrong root cause from what survived.
    """
    try:
        raw = conn.get(conn.platform.path("job_trace", project=project, job=job))
        text = raw if isinstance(raw, str) else str(raw or "")
        lines = text.splitlines()
        requested = max(1, int(tail_lines))
        tail = lines[-requested:]
        truncated = len(lines) > len(tail)
        joined = "\n".join(tail)
        chars_truncated = len(joined) > _MAX_TRACE_CHARS
        return {
            "project": s(project),
            "job": s(job),
            "totalLines": len(lines),
            "tailLines": len(tail),
            "returned": len(tail),
            "limit": requested,
            "truncated": truncated,
            "charsTruncated": chars_truncated,
            "trace": s(joined[-_MAX_TRACE_CHARS:], _MAX_TRACE_CHARS),
        }
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "project": s(project), "job": s(job)}

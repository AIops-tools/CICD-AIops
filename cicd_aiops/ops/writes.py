"""Governed CI/CD writes — the only state-changing operations in the tool.

Every write reads the object's current state **before** it changes anything,
so the harness records a faithful undo / audit trail (the before-state is
fetched via a real GET, never guessed):

  * ``retry_pipeline`` / ``cancel_pipeline`` — capture the pipeline's prior
    status; irreversible (a new run / a stopped run cannot be un-done), so
    priorState only, no undo.
  * ``pause_runner`` / ``resume_runner`` — capture the runner's prior paused
    flag; a true undo pair (each is the other's inverse).
  * ``delete_artifacts`` — the HIGH tier: captures the artifact count + bytes
    that are about to disappear (priorState only — deletion is irreversible).
  * ``update_branch_protection`` — captures the branch's prior protection
    settings; undo replays this same tool with the prior settings.

Platform notes: runner administration, pipeline retry/cancel and artifact
deletion are GitLab surfaces; on Gitea the platform registry raises its
standard teaching error listing what *is* available.

Each function returns a plain descriptor; the MCP layer adds dry-run + the
governance harness (risk tier + audit + undo).
"""

from __future__ import annotations

from typing import Any

from cicd_aiops.connection import CicdApiError
from cicd_aiops.governance import mark_unknown
from cicd_aiops.ops import artifacts as artifact_ops
from cicd_aiops.ops import pipelines as pipe_ops
from cicd_aiops.ops import repos as repo_ops
from cicd_aiops.ops import runners as runner_ops
from cicd_aiops.ops._util import age_days, as_int, s
from cicd_aiops.platform import GITLAB

# ── pipeline retry / cancel (priorState only — irreversible) ─────────────────


def _pipeline_prior_status(conn: Any, project: str, pipeline: str) -> str | None:
    prior = pipe_ops.pipeline_detail(conn, project, pipeline)
    return prior.get("status") if "error" not in prior else None


def retry_pipeline(conn: Any, project: str, pipeline: str) -> dict:
    """[WRITE][med] Retry a failed/canceled pipeline, capturing its prior status.

    Irreversible (it starts a new run) — priorState is recorded for the audit
    trail, no undo.
    """
    was_status = _pipeline_prior_status(conn, project, pipeline)
    out = conn.post(conn.platform.path("pipeline_retry", project=project, pipeline=pipeline))
    new_id = out.get("id") if isinstance(out, dict) else None
    return {
        "action": "retry_pipeline",
        "project": s(project),
        "pipeline": s(pipeline),
        "priorState": {"status": was_status},
        "newPipeline": s(new_id) if new_id is not None else s(pipeline),
    }


def cancel_pipeline(conn: Any, project: str, pipeline: str) -> dict:
    """[WRITE][med] Cancel a running pipeline, capturing its prior status.

    Irreversible (the stopped run cannot be resumed; a retry is a new run) —
    priorState is recorded for the audit trail, no undo.
    """
    was_status = _pipeline_prior_status(conn, project, pipeline)
    conn.post(conn.platform.path("pipeline_cancel", project=project, pipeline=pipeline))
    return {
        "action": "cancel_pipeline",
        "project": s(project),
        "pipeline": s(pipeline),
        "priorState": {"status": was_status},
        "canceled": True,
    }


# ── runner pause / resume (reversible undo pair) ─────────────────────────────


def _runner_prior_paused(conn: Any, runner: str) -> bool | None:
    prior = runner_ops.runner_detail(conn, runner)
    return bool(prior.get("paused")) if "error" not in prior else None


def pause_runner(conn: Any, runner: str) -> dict:
    """[WRITE][med] Pause a runner (stops it picking up new jobs). Undo: resume."""
    was_paused = _runner_prior_paused(conn, runner)
    conn.put(conn.platform.path("runner_update", runner=runner), json={"paused": True})
    return {
        "action": "pause_runner",
        "runner": s(runner),
        "paused": True,
        "priorState": {"paused": was_paused},
    }


def resume_runner(conn: Any, runner: str) -> dict:
    """[WRITE][med] Resume a paused runner. Undo: pause."""
    was_paused = _runner_prior_paused(conn, runner)
    conn.put(conn.platform.path("runner_update", runner=runner), json={"paused": False})
    return {
        "action": "resume_runner",
        "runner": s(runner),
        "paused": False,
        "priorState": {"paused": was_paused},
    }


# ── artifact deletion (high — irreversible, priorState = bytes/count) ────────

#: The job log. Listed among a job's artifacts, but not deleted with them.
_TRACE_FILE_TYPE = "trace"


def delete_artifacts(conn: Any, project: str, older_than_days: float = 0.0) -> dict:
    """[WRITE][high] Delete a project's artifacts (all, or older than N days).

    IRREVERSIBLE — before deleting, the current artifact inventory is read so
    priorState records exactly how many files/bytes are being destroyed.
    ``older_than_days > 0`` deletes per-job only the artifacts created before
    the cutoff; ``0`` uses the server's bulk-delete (eligible artifacts).
    """
    inventory = artifact_ops.list_artifacts(conn, project)
    rows = inventory.get("artifacts", []) if "error" not in inventory else []
    # The inventory read is itself bounded; say so rather than letting a
    # partial count read as an exact one.
    inventory_partial = bool(
        inventory.get("truncated") or inventory.get("jobScanTruncated")
    )
    if older_than_days and older_than_days > 0:
        matching = [
            a for a in rows if (age_days(a.get("createdAt")) or 0) >= older_than_days
        ]
        job_ids = sorted({a["jobId"] for a in matching if a.get("jobId")})
        for job_id in job_ids:
            conn.delete(
                conn.platform.path("job_artifacts_delete", project=project, job=job_id)
            )
        scope = f"older than {older_than_days:g} days"
        # The job log is listed as an artifact but survives this endpoint —
        # measured on GitLab 19.2.1: after deleting job artifacts, every
        # job.log (file_type "trace") was still there. Counting them as
        # destroyed over-reported an irreversible deletion by three files.
        deleted_rows = [a for a in matching if a.get("fileType") != _TRACE_FILE_TYPE]
        queued = False
    else:
        conn.delete(conn.platform.path("artifacts_delete", project=project))
        scope = "all eligible artifacts (server bulk delete)"
        deleted_rows = rows
        # GitLab answers the project-wide bulk delete with **202 Accepted**: the
        # request is queued, not performed, and the server decides for itself
        # which artifacts are *eligible* (locked ones are kept). Measured on
        # GitLab 19.2.1: 202, and 100 seconds later all seven artifacts were
        # still present — while this function reported them destroyed and the
        # audit row said `ok`. That is bug class #13 (submitted != completed) in
        # its worst form, because the claim is about an irreversible deletion.
        queued = True
    prior = {
        "count": len(deleted_rows),
        "bytes": sum(as_int(a.get("sizeBytes")) for a in deleted_rows),
        "complete": not inventory_partial,
    }
    if queued:
        out = mark_unknown({
            "action": "delete_artifacts",
            "project": s(project),
            "scope": scope,
            # NOT priorState-as-destroyed: this is what existed when the request
            # was accepted, which is an upper bound on what may be removed.
            "inventoryAtRequest": prior,
        })
        # mark_unknown's stock note says no usable response came back. Here one
        # did — a 202 — so the reason for the uncertainty is different and the
        # note is replaced rather than left to mislead.
        out["note"] = (
            "Queued, not confirmed. The server accepted the bulk delete (202) "
            "and performs it asynchronously, removing only the artifacts it "
            "considers eligible — locked artifacts are kept, so the count above "
            "is an UPPER bound on what will disappear, not a record of what was "
            "destroyed. Re-read 'artifacts list' to see the actual outcome."
        )
        return out
    return {
        "action": "delete_artifacts",
        "project": s(project),
        "scope": scope,
        "priorState": prior,
        "note": (
            "Irreversible — priorState records what was destroyed; no undo."
            if not inventory_partial
            else "Irreversible — no undo. priorState is a LOWER BOUND: the "
            "artifact inventory it was measured from was itself truncated."
        ),
    }


# ── branch protection (reversible — undo replays prior settings) ─────────────


def _capture_protection(conn: Any, project: str, branch: str) -> dict | None:
    """Current protection settings for a branch, or None when unprotected."""
    try:
        raw = conn.get(conn.platform.path("protected_branch", project=project, branch=branch))
    except CicdApiError as exc:
        if exc.status_code == 404:
            return None
        raise
    return repo_ops.norm_protection(
        raw if isinstance(raw, dict) else {}
    )


def update_branch_protection(
    conn: Any,
    project: str,
    branch: str,
    protect: bool = True,
    allow_force_push: bool = False,
) -> dict:
    """[WRITE][med] Protect/unprotect a branch, capturing prior settings.

    Reads the branch's current protection first so priorState reflects what it
    *was* (drives a faithful, replayable undo: re-run this tool with the prior
    settings).
    """
    prior = _capture_protection(conn, project, branch)
    if protect:
        if conn.target.platform == GITLAB:
            if prior is not None:
                conn.patch(
                    conn.platform.path("protected_branch", project=project, branch=branch),
                    json={"allow_force_push": bool(allow_force_push)},
                )
            else:
                conn.post(
                    conn.platform.path("protected_branches", project=project),
                    params={
                        "name": s(branch, 128),
                        "allow_force_push": str(bool(allow_force_push)).lower(),
                    },
                )
        else:
            payload = {
                "branch_name": s(branch, 128),
                "enable_force_push": bool(allow_force_push),
            }
            if prior is not None:
                conn.patch(
                    conn.platform.path("protected_branch", project=project, branch=branch),
                    json=payload,
                )
            else:
                conn.post(
                    conn.platform.path("protected_branches", project=project), json=payload
                )
    else:
        if prior is not None:
            conn.delete(
                conn.platform.path("protected_branch", project=project, branch=branch)
            )
    return {
        "action": "update_branch_protection",
        "project": s(project),
        "branch": s(branch),
        "protect": bool(protect),
        "allowForcePush": bool(allow_force_push),
        "priorState": {
            "protected": prior is not None,
            "allowForcePush": bool(prior.get("allowForcePush")) if prior else None,
        },
    }

"""Governed CI/CD-write MCP tools (the only state-changing tools).

Every tool is wrapped with the governance harness (audit + risk tier) and takes
a ``dry_run`` preview. Reversible writes pass an ``undo=``
callback that turns the fetched before-state into an inverse descriptor the
harness records; irreversible ones (pipeline retry/cancel, artifact deletion)
record priorState only.

Risk tiers: delete_artifacts = high (destroys data); retry_pipeline /
cancel_pipeline / pause_runner / resume_runner / update_branch_protection =
medium.
"""

from typing import Any, Optional

from cicd_aiops.governance import governed_tool
from cicd_aiops.ops import writes as ops
from mcp_server._shared import _get_connection, mcp, tool_errors


def _write_path(conn: Any, resource: str, **fmt: Any) -> str:
    """Resolve the REST path a write will call — the preview's platform guard.

    A ``dry_run`` returns before the ops layer runs, so without this the preview
    never touches the platform registry and happily describes a write that the
    real call is about to reject with ``UnsupportedResource`` (runner
    administration, pipeline retry/cancel and bulk artifact deletion exist on
    GitLab but not on Gitea). Resolving the path here makes the preview run the
    same registry lookup the write does, so an unsupported surface refuses at
    preview time instead of promising an operation that cannot happen.

    Called with no ``fmt`` it returns the unformatted template — still a real
    registry lookup, still raising for an unmapped resource — which is what a
    per-job path wants, since which jobs are hit is data-dependent.
    """
    return conn.platform.path(resource, **fmt)


# ── undo descriptors (built from the fetched before-state) ──────────────────


def _pause_runner_undo(params: dict[str, Any], result: Any) -> Optional[dict]:
    """Inverse of pause_runner: resume, but only if it was NOT already paused."""
    if not isinstance(result, dict):
        return None
    prior = (result.get("priorState") or {}).get("paused")
    if prior:  # it was already paused before — undo must not resume it
        return None
    return {
        "tool": "resume_runner",
        "params": {"runner": params.get("runner")},
        "skill": "cicd-aiops",
        "note": "Inverse of pause_runner: resume the runner.",
    }


def _resume_runner_undo(params: dict[str, Any], result: Any) -> Optional[dict]:
    """Inverse of resume_runner: pause, but only if it WAS paused before."""
    if not isinstance(result, dict):
        return None
    prior = (result.get("priorState") or {}).get("paused")
    if not prior:  # it was not paused before — nothing to restore
        return None
    return {
        "tool": "pause_runner",
        "params": {"runner": params.get("runner")},
        "skill": "cicd-aiops",
        "note": "Inverse of resume_runner: pause the runner again.",
    }


def _protection_undo(params: dict[str, Any], result: Any) -> Optional[dict]:
    """Inverse of update_branch_protection: replay the prior settings."""
    if not isinstance(result, dict):
        return None
    prior = result.get("priorState") or {}
    if prior.get("protected"):
        undo_params = {
            "project": params.get("project"),
            "branch": params.get("branch"),
            "protect": True,
            "allow_force_push": bool(prior.get("allowForcePush")),
        }
        note = "Restore the branch's prior protection settings."
    else:
        undo_params = {
            "project": params.get("project"),
            "branch": params.get("branch"),
            "protect": False,
        }
        note = "The branch was unprotected before — remove the protection again."
    return {
        "tool": "update_branch_protection",
        "params": undo_params,
        "skill": "cicd-aiops",
        "note": f"Inverse of update_branch_protection: {note}",
    }


# ── pipeline retry / cancel (priorState only — irreversible) ─────────────────


@mcp.tool()
@governed_tool(risk_level="medium")
@tool_errors("dict")
def retry_pipeline(
    project: str,
    pipeline: str,
    dry_run: bool = False,
    target: Optional[str] = None,
) -> dict:
    """[WRITE][risk=medium] Retry a failed/canceled pipeline.

    Reads the pipeline first so priorState records the status it had before the
    retry. Irreversible (a retry is a new run) — no undo. Pass dry_run=True to
    preview.

    Args:
        project: Project id or full path ('group/project' / 'owner/repo').
        pipeline: Pipeline id (from list_pipelines).
        dry_run: If True, preview without retrying.
        target: Server target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        return {
            "dryRun": True,
            "wouldRetry": {
                "project": project,
                "pipeline": pipeline,
                "path": _write_path(conn, "pipeline_retry", project=project, pipeline=pipeline),
            },
        }
    return ops.retry_pipeline(conn, project, pipeline)


@mcp.tool()
@governed_tool(risk_level="medium")
@tool_errors("dict")
def cancel_pipeline(
    project: str,
    pipeline: str,
    dry_run: bool = False,
    target: Optional[str] = None,
) -> dict:
    """[WRITE][risk=medium] Cancel a running pipeline.

    Reads the pipeline first so priorState records the status it had before the
    cancel. Irreversible (the stopped run cannot be resumed) — no undo. Pass
    dry_run=True to preview.

    Args:
        project: Project id or full path.
        pipeline: Pipeline id (from list_pipelines).
        dry_run: If True, preview without canceling.
        target: Server target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        return {
            "dryRun": True,
            "wouldCancel": {
                "project": project,
                "pipeline": pipeline,
                "path": _write_path(conn, "pipeline_cancel", project=project, pipeline=pipeline),
            },
        }
    return ops.cancel_pipeline(conn, project, pipeline)


# ── runner pause / resume (reversible undo pair) ─────────────────────────────


@mcp.tool()
@governed_tool(risk_level="medium", undo=_pause_runner_undo)
@tool_errors("dict")
def pause_runner(
    runner: str,
    dry_run: bool = False,
    target: Optional[str] = None,
) -> dict:
    """[WRITE][risk=medium] Pause a runner; reversible (undo resumes it).

    Reads the runner first so the harness records its prior paused state.
    A paused runner stops picking up new jobs; running jobs finish. Pass
    dry_run=True to preview.

    Args:
        runner: Runner id (from list_runners).
        dry_run: If True, preview without pausing.
        target: Server target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        return {
            "dryRun": True,
            "wouldPause": {
                "runner": runner,
                "path": _write_path(conn, "runner_update", runner=runner),
            },
        }
    return ops.pause_runner(conn, runner)


@mcp.tool()
@governed_tool(risk_level="medium", undo=_resume_runner_undo)
@tool_errors("dict")
def resume_runner(
    runner: str,
    dry_run: bool = False,
    target: Optional[str] = None,
) -> dict:
    """[WRITE][risk=medium] Resume a paused runner; reversible (undo pauses it).

    Reads the runner first so the harness records its prior paused state. Pass
    dry_run=True to preview.

    Args:
        runner: Runner id (from list_runners).
        dry_run: If True, preview without resuming.
        target: Server target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        return {
            "dryRun": True,
            "wouldResume": {
                "runner": runner,
                "path": _write_path(conn, "runner_update", runner=runner),
            },
        }
    return ops.resume_runner(conn, runner)


# ── artifact deletion (high — irreversible) ──────────────────────────────────


@mcp.tool()
@governed_tool(risk_level="high")
@tool_errors("dict")
def delete_artifacts(
    project: str,
    older_than_days: float = 0.0,
    dry_run: bool = False,
    target: Optional[str] = None,
) -> dict:
    """[WRITE][risk=high] Delete a project's artifacts (all, or older than N days).

    IRREVERSIBLE — reads the artifact inventory first so priorState records the
    file count and bytes being destroyed; no undo. Pass dry_run=True to preview
    (reports what would be reclaimed without deleting).

    Args:
        project: Project id or full path.
        older_than_days: Only delete artifacts created before this many days
            ago; 0 = the server's bulk delete of all eligible artifacts.
        dry_run: If True, preview without deleting.
        target: Server target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        from cicd_aiops.ops import artifacts as artifact_ops

        # Resolve the delete path FIRST, before the inventory read: on a
        # platform with no artifact-deletion surface this raises the same
        # teaching error the real write would, so the preview refuses rather
        # than spending a scan to describe a deletion that cannot happen. The
        # per-job path stays a template — which jobs are hit is data-dependent.
        if older_than_days > 0:
            path = _write_path(conn, "job_artifacts_delete")
        else:
            path = _write_path(conn, "artifacts_delete", project=project)
        inventory = artifact_ops.list_artifacts(conn, project)
        return {
            "dryRun": True,
            "wouldDelete": {
                "project": project,
                "olderThanDays": older_than_days,
                "path": path,
                # "artifactsFound", not "total": the listing envelope has no
                # "total" by design (it only ever sees the already-sliced page),
                # so this read was always None — the preview of a HIGH-risk,
                # irreversible delete could never say how many artifacts it
                # would remove, which is the one number the operator needs.
                # artifactsFound counts EVERY artifact found, not just the
                # returned page, so it is the blast radius.
                "currentCount": inventory.get("artifactsFound"),
                "currentBytes": inventory.get("totalBytes"),
                "expiredButKept": inventory.get("expiredButKept"),
            },
        }
    return ops.delete_artifacts(conn, project, older_than_days=older_than_days)


# ── branch protection (reversible — undo replays prior settings) ─────────────


@mcp.tool()
@governed_tool(risk_level="medium", undo=_protection_undo)
@tool_errors("dict")
def update_branch_protection(
    project: str,
    branch: str,
    protect: bool = True,
    allow_force_push: bool = False,
    dry_run: bool = False,
    target: Optional[str] = None,
) -> dict:
    """[WRITE][risk=medium] Protect/unprotect a branch; reversible.

    Reads the branch's current protection first so the harness records an undo
    that replays this same tool with the prior settings. Pass dry_run=True to
    preview.

    Args:
        project: Project id or full path.
        branch: Branch name (from list_branches).
        protect: True to protect the branch, False to remove protection.
        allow_force_push: Whether the protection permits force-push (default
            False — the safe setting).
        dry_run: If True, preview without changing.
        target: Server target name from config; omit for the default.
    """
    conn = _get_connection(target)
    if dry_run:
        return {
            "dryRun": True,
            "wouldUpdate": {
                "project": project,
                "branch": branch,
                "protect": protect,
                "allowForcePush": allow_force_push,
            },
        }
    return ops.update_branch_protection(
        conn, project, branch, protect=protect, allow_force_push=allow_force_push
    )

"""Pipeline reads — list, detail, jobs, trace tail (read-only).

Platform-neutral pipeline surface: GitLab pipelines (``/pipelines``) and Gitea
Actions runs (``/actions/runs``) return the same concepts under different field
names, reconciled through the shared field pickers. Nothing here mutates a
pipeline — retry/cancel live in :mod:`cicd_aiops.ops.writes`.
"""

from __future__ import annotations

from typing import Any

from cicd_aiops.ops._util import as_obj, pick, s

_MAX_LIST = 100
DEFAULT_TRACE_TAIL_LINES = 60
_MAX_TRACE_CHARS = 8000


def norm_pipeline(r: dict) -> dict:
    """Normalise one pipeline/run row across GitLab / Gitea field names."""
    return {
        "id": s(pick(r, "id")),
        "status": s(pick(r, "status", "conclusion"), 32).lower(),
        "ref": s(pick(r, "ref", "head_branch")),
        "sha": s(pick(r, "sha", "head_sha"), 64),
        "source": s(pick(r, "source", "event", "trigger_event")),
        "createdAt": s(pick(r, "created_at")),
        "updatedAt": s(pick(r, "updated_at")),
        "durationSec": pick(r, "duration", default=None),
        "webUrl": s(pick(r, "web_url", "url", "html_url")),
    }


def norm_job(r: dict) -> dict:
    """Normalise one job row across GitLab / Gitea field names."""
    return {
        "id": s(pick(r, "id")),
        "name": s(pick(r, "name")),
        "stage": s(pick(r, "stage", default="")),
        "status": s(pick(r, "status", "conclusion"), 32).lower(),
        "failureReason": s(pick(r, "failure_reason", default="")),
        "createdAt": s(pick(r, "created_at")),
        "startedAt": s(pick(r, "started_at")),
        "finishedAt": s(pick(r, "finished_at", "completed_at")),
        "durationSec": pick(r, "duration", default=None),
        "runner": s(pick(as_obj(r.get("runner")), "description", "name", default="")),
        "tags": [s(t, 64) for t in (r.get("tag_list") or []) if isinstance(t, str)],
        "queuedDurationSec": pick(r, "queued_duration", default=None),
    }


def list_pipelines(
    conn: Any, project: str, status: str | None = None, limit: int = 20
) -> dict:
    """[READ] Recent pipelines/runs for a project, newest first."""
    try:
        params: dict[str, Any] = {"per_page": min(max(1, int(limit)), _MAX_LIST)}
        if status:
            params["status"] = s(status, 32).lower()
        rows = conn.platform.rows(
            conn.get(conn.platform.path("pipelines", project=project), params=params)
        )
        pipelines = [norm_pipeline(r) for r in rows][: max(1, int(limit))]
        return {"project": s(project), "total": len(pipelines), "pipelines": pipelines}
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


def pipeline_jobs(conn: Any, project: str, pipeline: str) -> dict:
    """[READ] Jobs of one pipeline/run with status + failure reason."""
    try:
        rows = conn.platform.rows(
            conn.get(conn.platform.path("pipeline_jobs", project=project, pipeline=pipeline))
        )
        jobs = [norm_job(r) for r in rows]
        return {
            "project": s(project),
            "pipeline": s(pipeline),
            "total": len(jobs),
            "jobs": jobs,
        }
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "project": s(project), "pipeline": s(pipeline)}


def job_trace_tail(
    conn: Any, project: str, job: str, tail_lines: int = DEFAULT_TRACE_TAIL_LINES
) -> dict:
    """[READ] The tail of one job's log/trace (the part that explains failures)."""
    try:
        raw = conn.get(conn.platform.path("job_trace", project=project, job=job))
        text = raw if isinstance(raw, str) else str(raw or "")
        lines = text.splitlines()
        tail = lines[-max(1, int(tail_lines)):]
        joined = "\n".join(tail)[-_MAX_TRACE_CHARS:]
        return {
            "project": s(project),
            "job": s(job),
            "totalLines": len(lines),
            "tailLines": len(tail),
            "trace": s(joined, _MAX_TRACE_CHARS),
        }
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "project": s(project), "job": s(job)}

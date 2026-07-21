"""Project/repository reads — list, detail, storage statistics (read-only).

Platform-neutral project surface: GitLab ``/api/v4/projects`` and Gitea
``/api/v1/repos/search`` return the same concepts under different field names,
reconciled through the shared field pickers. GitLab exposes per-project storage
statistics inline (``statistics=true``); Gitea reports a repo ``size`` (KiB).
"""

from __future__ import annotations

from typing import Any

from cicd_aiops.ops._util import as_int, as_obj, listing, opt, page_limit, pick, s
from cicd_aiops.platform import GITLAB

_MAX_LIST = 100


def _norm_project(r: dict) -> dict:
    """Normalise one project row across GitLab / Gitea field names.

    Artifact and total-storage bytes come from GitLab's per-project
    ``statistics``; Gitea has no equivalent. Where they are unavailable they
    are reported as ``None`` — NOT as ``0``. A zero here would read as "this
    project stores no artifacts", which is a different (and wrong) claim from
    "this platform does not report artifact storage".
    """
    stats = as_obj(r.get("statistics"))
    return {
        "id": s(pick(r, "id")),
        "name": opt(pick(r, "name")),
        "path": s(pick(r, "path_with_namespace", "full_name", "path")),
        "defaultBranch": opt(pick(r, "default_branch")),
        "archived": bool(pick(r, "archived", default=False)),
        "lastActivity": opt(pick(r, "last_activity_at", "updated_at")),
        # Byte counts are integers — as_int, not num (which printed 3870.0 bytes).
        "repoBytes": as_int(
            pick(stats, "repository_size", default=as_int(r.get("size")) * 1024)
        ),
        "artifactsBytes": (
            as_int(stats["job_artifacts_size"]) if "job_artifacts_size" in stats else None
        ),
        "storageBytes": as_int(stats["storage_size"]) if "storage_size" in stats else None,
    }


def list_projects(conn: Any, search: str | None = None, limit: int = 50) -> dict:
    """[READ] Projects/repositories the token can see, normalized.

    Returns ``{projects, returned, limit, truncated}``; one row beyond ``limit``
    is requested so ``truncated`` is measured, not inferred from a full page.
    """
    try:
        requested, per_page = page_limit(limit, _MAX_LIST)
        params: dict[str, Any] = {"per_page": per_page}
        if conn.target.platform == GITLAB:
            params["statistics"] = "true"
            params["membership"] = "true"
            params["order_by"] = "last_activity_at"
        if search:
            params["q" if conn.target.platform != GITLAB else "search"] = s(search, 64)
        rows = conn.platform.rows(conn.get(conn.platform.path("projects"), params=params))
        truncated = len(rows) > requested
        projects = [_norm_project(r) for r in rows[:requested]]
        return listing("projects", projects, requested, truncated)
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}


def project_detail(conn: Any, project: str) -> dict:
    """[READ] One project's detail (GitLab: id or full path; Gitea: owner/repo)."""
    try:
        params = {"statistics": "true"} if conn.target.platform == GITLAB else None
        raw = conn.get(conn.platform.path("project", project=project), params=params)
        detail = _norm_project(as_obj(conn.platform.normalise(raw)))
        detail["project"] = s(project)
        return detail
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "project": s(project)}


def pull_projects_with_stats(conn: Any, limit: int = 100) -> list[dict]:
    """[READ] Live project rows with storage numbers (feeds the bloat RCA)."""
    out = list_projects(conn, limit=limit)
    return out.get("projects", []) if isinstance(out, dict) and "error" not in out else []

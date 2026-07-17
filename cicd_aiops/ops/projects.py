"""Project/repository reads — list, detail, storage statistics (read-only).

Platform-neutral project surface: GitLab ``/api/v4/projects`` and Gitea
``/api/v1/repos/search`` return the same concepts under different field names,
reconciled through the shared field pickers. GitLab exposes per-project storage
statistics inline (``statistics=true``); Gitea reports a repo ``size`` (KiB).
"""

from __future__ import annotations

from typing import Any

from cicd_aiops.ops._util import as_obj, num, pick, s
from cicd_aiops.platform import GITLAB

_MAX_LIST = 200


def _norm_project(r: dict) -> dict:
    """Normalise one project row across GitLab / Gitea field names."""
    stats = as_obj(r.get("statistics"))
    return {
        "id": s(pick(r, "id")),
        "path": s(pick(r, "path_with_namespace", "full_name", "path")),
        "defaultBranch": s(pick(r, "default_branch")),
        "archived": bool(pick(r, "archived", default=False)),
        "lastActivity": s(pick(r, "last_activity_at", "updated_at")),
        "repoBytes": num(
            pick(stats, "repository_size", default=num(r.get("size")) * 1024)
        ),
        "artifactsBytes": num(pick(stats, "job_artifacts_size", default=0)),
        "storageBytes": num(pick(stats, "storage_size", default=0)),
    }


def list_projects(conn: Any, search: str | None = None, limit: int = 50) -> dict:
    """[READ] Projects/repositories the token can see, normalized."""
    try:
        params: dict[str, Any] = {"per_page": min(max(1, int(limit)), _MAX_LIST)}
        if conn.target.platform == GITLAB:
            params["statistics"] = "true"
            params["membership"] = "true"
            params["order_by"] = "last_activity_at"
        if search:
            params["q" if conn.target.platform != GITLAB else "search"] = s(search, 64)
        rows = conn.platform.rows(conn.get(conn.platform.path("projects"), params=params))
        projects = [_norm_project(r) for r in rows][: max(1, int(limit))]
        return {"total": len(projects), "projects": projects}
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

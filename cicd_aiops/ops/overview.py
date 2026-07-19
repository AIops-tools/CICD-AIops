"""One-shot CI/CD server overview (read-only).

A single call an operator can lead with: platform + version, token identity,
project count, and (where the platform supports it) runner online/offline
counts. Resilient — a failing sub-call degrades to a partial summary with an
``errors`` list.
"""

from __future__ import annotations

from typing import Any

from cicd_aiops.ops import projects as project_ops
from cicd_aiops.ops import runners as runner_ops
from cicd_aiops.ops import server as server_ops


def cicd_overview(conn: Any) -> dict:
    """[READ] Summary: platform/version + token identity + projects + runners."""
    errors: list[str] = []

    ver = server_ops.server_version(conn)
    if isinstance(ver, dict) and "error" in ver:
        errors.append(f"version: {ver['error']}")
        ver = {}

    user = server_ops.current_user(conn)
    if isinstance(user, dict) and "error" in user:
        errors.append(f"user: {user['error']}")
        user = {}

    pl = project_ops.list_projects(conn, limit=100)
    projects_ok = isinstance(pl, dict) and "error" not in pl
    project_total = pl.get("returned") if projects_ok else None
    projects_truncated = bool(pl.get("truncated")) if projects_ok else False
    if isinstance(pl, dict) and "error" in pl:
        errors.append(f"projects: {pl['error']}")

    # Runner administration is a GitLab-only surface. On Gitea the counts stay
    # null and 'runnersSupported' says why — a null that means "this platform
    # has no runner API" must never be read as "there are no runners".
    runners_supported = conn.platform.supports("runners")
    runners_total = runners_online = None
    runners_truncated = False
    if runners_supported:
        rl = runner_ops.list_runners(conn)
        if isinstance(rl, dict) and "error" not in rl:
            rows = rl.get("runners", [])
            runners_total = rl.get("returned")
            runners_online = sum(1 for r in rows if r.get("online"))
            runners_truncated = bool(rl.get("truncated"))
        elif isinstance(rl, dict):
            errors.append(f"runners: {rl['error']}")

    return {
        "platform": conn.target.platform,
        "target": conn.target.name,
        "version": ver.get("version"),
        "authenticatedAs": user.get("username"),
        "projectsTotal": project_total,
        "projectsTruncated": projects_truncated,
        "runnersSupported": runners_supported,
        "runnersTotal": runners_total,
        "runnersOnline": runners_online,
        "runnersTruncated": runners_truncated,
        "errors": errors,
        "note": (
            "Counts are what this call returned, not server-wide totals; a "
            "'*Truncated' flag means there were more. runnersSupported=false "
            "means this platform has no runner API — the null runner counts "
            "are 'not available here', not 'zero'."
        ),
    }

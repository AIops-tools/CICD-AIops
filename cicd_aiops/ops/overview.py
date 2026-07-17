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
    project_total = pl.get("total") if isinstance(pl, dict) and "error" not in pl else None
    if isinstance(pl, dict) and "error" in pl:
        errors.append(f"projects: {pl['error']}")

    runners_total = runners_online = None
    if conn.platform.supports("runners"):
        rl = runner_ops.list_runners(conn)
        if isinstance(rl, dict) and "error" not in rl:
            rows = rl.get("runners", [])
            runners_total = rl.get("total")
            runners_online = sum(1 for r in rows if r.get("online"))
        elif isinstance(rl, dict):
            errors.append(f"runners: {rl['error']}")

    return {
        "platform": conn.target.platform,
        "target": conn.target.name,
        "version": ver.get("version"),
        "authenticatedAs": user.get("username"),
        "projectsTotal": project_total,
        "runnersTotal": runners_total,
        "runnersOnline": runners_online,
        "errors": errors,
    }

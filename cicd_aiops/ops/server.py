"""Server reads — version and token identity (read-only).

The "is this CI/CD server healthy and is my token sane?" surface,
platform-neutral: each op asks the platform for the right path and unwraps the
payload through the shared helpers, so the same function serves GitLab and
Gitea. Every call is resilient — a transport/parse failure surfaces as
``{"error": ...}`` instead of raising, and all server text is sanitised via
``s``.
"""

from __future__ import annotations

from typing import Any

from cicd_aiops.ops._util import as_obj, pick, s


def server_version(conn: Any) -> dict:
    """[READ] Server version and revision."""
    try:
        obj = as_obj(conn.get(conn.platform.path("version")))
        return {
            "platform": conn.target.platform,
            "version": s(pick(obj, "version")),
            "revision": s(pick(obj, "revision", "enterprise", default="")),
        }
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}


def current_user(conn: Any) -> dict:
    """[READ] The token's identity — who the API sees you as (scope probe)."""
    try:
        obj = as_obj(conn.get(conn.platform.path("current_user")))
        return {
            "platform": conn.target.platform,
            "username": s(pick(obj, "username", "login")),
            "name": s(pick(obj, "name", "full_name")),
            "isAdmin": bool(pick(obj, "is_admin", "admin", default=False)),
            "state": s(pick(obj, "state", "visibility", default="active")),
        }
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}

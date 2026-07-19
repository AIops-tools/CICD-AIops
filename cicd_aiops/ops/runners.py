"""Runner reads — fleet list and per-runner detail (read-only).

GitLab exposes runner administration under ``/api/v4/runners/...``; Gitea has
no public runner-administration API in v1, so asking a Gitea target raises the
platform registry's teaching error listing what *is* available. Pause/resume
live in :mod:`cicd_aiops.ops.writes`.
"""

from __future__ import annotations

from typing import Any

from cicd_aiops.ops._util import as_obj, listing, opt, page_limit, pick, s

_MAX_LIST = 100


def norm_runner(r: dict) -> dict:
    """Normalise one runner row.

    A runner that has never contacted the server has no ``contactedAt``; it
    comes back as ``None``, not ``""``, so "never seen" cannot be mistaken for
    "seen, timestamp empty".
    """
    return {
        "id": s(pick(r, "id")),
        "description": opt(pick(r, "description", "name")),
        "status": s(pick(r, "status"), 32).lower(),
        "paused": bool(pick(r, "paused", default=not pick(r, "active", default=True))),
        "online": bool(pick(r, "online", default=False)),
        "isShared": bool(pick(r, "is_shared", default=False)),
        "runnerType": opt(pick(r, "runner_type")),
        "tags": [s(t, 64) for t in (r.get("tag_list") or []) if isinstance(t, str)],
        "contactedAt": opt(pick(r, "contacted_at")),
    }


def list_runners(conn: Any, status: str | None = None, limit: int = 100) -> dict:
    """[READ] All runners visible to the token, offline first.

    GitLab-only: Gitea has no runner-administration API, so the platform
    registry raises its teaching ``KeyError`` instead — that is a "wrong
    platform for this question" signal, not a tool failure.

    Returns ``{runners, returned, limit, truncated}``; one row beyond ``limit``
    is requested so ``truncated`` is measured. Rows are sorted offline/paused
    first *before* the cut, so the most urgent runners survive truncation.
    """
    try:
        requested, per_page = page_limit(limit, _MAX_LIST)
        params: dict[str, Any] = {"per_page": per_page}
        if status:
            params["status"] = s(status, 32).lower()
        rows = conn.platform.rows(conn.get(conn.platform.path("runners"), params=params))
        runners = [norm_runner(r) for r in rows]
        runners.sort(key=lambda r: (r["online"], not r["paused"]))
        truncated = len(runners) > requested
        return listing("runners", runners[:requested], requested, truncated)
    except KeyError:
        raise  # teaching error from the platform registry (e.g. Gitea)
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200)}


def runner_detail(conn: Any, runner: str) -> dict:
    """[READ] One runner's full detail (incl. contacted_at, tags, paused).

    GitLab-only, like :func:`list_runners`; a Gitea target raises the platform
    registry's teaching error.
    """
    try:
        raw = conn.get(conn.platform.path("runner", runner=runner))
        obj = as_obj(conn.platform.normalise(raw))
        detail = norm_runner(obj)
        detail["architecture"] = opt(pick(obj, "architecture"))
        detail["version"] = opt(pick(obj, "version"))
        return detail
    except KeyError:
        raise  # teaching error from the platform registry (e.g. Gitea)
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "runner": s(runner)}


def pull_runners(conn: Any, limit: int = 200) -> list[dict]:
    """[READ] Live runner rows (feeds the runner-health RCA)."""
    out = list_runners(conn, limit=limit)
    return out.get("runners", []) if isinstance(out, dict) and "error" not in out else []

"""Repository-surface reads — merge/pull requests, branches, protection, releases.

Platform-neutral: GitLab merge requests and Gitea pull requests are the same
concept; both expose branches with commit dates and a branch-protection list.
All read-only; protection *changes* live in :mod:`cicd_aiops.ops.writes`.
"""

from __future__ import annotations

from typing import Any

from cicd_aiops.ops._util import as_obj, listing, opt, page_limit, pick, s

_MAX_LIST = 100


def norm_merge_request(r: dict) -> dict:
    """Normalise one merge/pull request row across GitLab / Gitea field names."""
    author = as_obj(r.get("author")) or as_obj(as_obj(r.get("user")))
    return {
        "id": s(pick(r, "iid", "number", "id")),
        "title": s(pick(r, "title"), 160),
        "state": s(pick(r, "state"), 32).lower(),
        "author": opt(pick(author, "username", "login")),
        "sourceBranch": opt(pick(r, "source_branch", default=pick(as_obj(r.get("head")), "ref"))),
        "targetBranch": opt(pick(r, "target_branch", default=pick(as_obj(r.get("base")), "ref"))),
        "createdAt": opt(pick(r, "created_at")),
        "updatedAt": opt(pick(r, "updated_at")),
        "draft": bool(pick(r, "draft", "work_in_progress", default=False)),
    }


def list_merge_requests(
    conn: Any, project: str, state: str = "opened", limit: int = 50
) -> dict:
    """[READ] Merge/pull requests for a project (default: open ones)."""
    try:
        want = s(state, 16).lower()
        # GitLab calls it 'opened'; Gitea 'open'. Send the platform's word.
        param_state = want
        if want in ("open", "opened"):
            param_state = "opened" if conn.platform.uses_private_token else "open"
        requested, per_page = page_limit(limit, _MAX_LIST)
        params = {"state": param_state, "per_page": per_page}
        rows = conn.platform.rows(
            conn.get(conn.platform.path("merge_requests", project=project), params=params)
        )
        truncated = len(rows) > requested
        mrs = [norm_merge_request(r) for r in rows[:requested]]
        return listing("mergeRequests", mrs, requested, truncated, project=s(project))
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "project": s(project)}


def norm_branch(r: dict) -> dict:
    """Normalise one branch row (last-commit date drives staleness)."""
    commit = as_obj(r.get("commit"))
    return {
        "name": s(pick(r, "name")),
        "default": bool(pick(r, "default", default=False)),
        "protected": bool(pick(r, "protected", default=False)),
        "lastCommitAt": opt(
            pick(commit, "committed_date", "timestamp", default=pick(r, "updated_at"))
        ),
    }


def list_branches(conn: Any, project: str, limit: int = 100) -> dict:
    """[READ] Branches with last-commit date and protected flag."""
    try:
        requested, per_page = page_limit(limit, _MAX_LIST)
        params = {"per_page": per_page}
        rows = conn.platform.rows(
            conn.get(conn.platform.path("branches", project=project), params=params)
        )
        truncated = len(rows) > requested
        branches = [norm_branch(r) for r in rows[:requested]]
        return listing("branches", branches, requested, truncated, project=s(project))
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "project": s(project)}


def norm_protection(r: dict) -> dict:
    """Normalise one branch-protection row across GitLab / Gitea field names."""
    return {
        "branch": s(pick(r, "name", "branch_name", "rule_name")),
        "allowForcePush": bool(pick(r, "allow_force_push", "enable_force_push", default=False)),
        "raw": {k: v for k, v in r.items() if isinstance(k, str)},
    }


def list_protected_branches(conn: Any, project: str, limit: int = _MAX_LIST) -> dict:
    """[READ] Branch-protection rules for a project.

    The endpoint returns the complete rule set, so truncation is measured
    against the full fetched list rather than by over-fetching a page.
    """
    try:
        rows = conn.platform.rows(
            conn.get(conn.platform.path("protected_branches", project=project))
        )
        requested = max(1, int(limit))
        truncated = len(rows) > requested
        protections = [norm_protection(r) for r in rows[:requested]]
        return listing(
            "protections", protections, requested, truncated, project=s(project)
        )
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "project": s(project)}


def list_releases(conn: Any, project: str, limit: int = 20) -> dict:
    """[READ] Releases for a project, newest first."""
    try:
        requested, per_page = page_limit(limit, _MAX_LIST)
        params = {"per_page": per_page}
        rows = conn.platform.rows(
            conn.get(conn.platform.path("releases", project=project), params=params)
        )
        truncated = len(rows) > requested
        releases = [
            {
                "tag": s(pick(r, "tag_name")),
                "name": opt(pick(r, "name"), 160),
                "createdAt": opt(pick(r, "created_at")),
                "draft": bool(pick(r, "draft", "upcoming_release", default=False)),
                "prerelease": bool(pick(r, "prerelease", default=False)),
            }
            for r in rows[:requested]
        ]
        return listing("releases", releases, requested, truncated, project=s(project))
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "project": s(project)}

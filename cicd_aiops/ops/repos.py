"""Repository-surface reads — merge/pull requests, branches, protection, releases.

Platform-neutral: GitLab merge requests and Gitea pull requests are the same
concept; both expose branches with commit dates and a branch-protection list.
All read-only; protection *changes* live in :mod:`cicd_aiops.ops.writes`.
"""

from __future__ import annotations

from typing import Any

from cicd_aiops.ops._util import as_obj, pick, s

_MAX_LIST = 100


def norm_merge_request(r: dict) -> dict:
    """Normalise one merge/pull request row across GitLab / Gitea field names."""
    author = as_obj(r.get("author")) or as_obj(as_obj(r.get("user")))
    return {
        "id": s(pick(r, "iid", "number", "id")),
        "title": s(pick(r, "title"), 160),
        "state": s(pick(r, "state"), 32).lower(),
        "author": s(pick(author, "username", "login", default="")),
        "sourceBranch": s(pick(r, "source_branch", default=s(pick(as_obj(r.get("head")), "ref")))),
        "targetBranch": s(pick(r, "target_branch", default=s(pick(as_obj(r.get("base")), "ref")))),
        "createdAt": s(pick(r, "created_at")),
        "updatedAt": s(pick(r, "updated_at")),
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
        params = {"state": param_state, "per_page": min(max(1, int(limit)), _MAX_LIST)}
        rows = conn.platform.rows(
            conn.get(conn.platform.path("merge_requests", project=project), params=params)
        )
        mrs = [norm_merge_request(r) for r in rows][: max(1, int(limit))]
        return {"project": s(project), "total": len(mrs), "mergeRequests": mrs}
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "project": s(project)}


def norm_branch(r: dict) -> dict:
    """Normalise one branch row (last-commit date drives staleness)."""
    commit = as_obj(r.get("commit"))
    return {
        "name": s(pick(r, "name")),
        "default": bool(pick(r, "default", default=False)),
        "protected": bool(pick(r, "protected", default=False)),
        "lastCommitAt": s(
            pick(
                commit,
                "committed_date",
                "timestamp",
                default=s(pick(r, "updated_at", default="")),
            )
        ),
    }


def list_branches(conn: Any, project: str, limit: int = 100) -> dict:
    """[READ] Branches with last-commit date and protected flag."""
    try:
        params = {"per_page": min(max(1, int(limit)), _MAX_LIST)}
        rows = conn.platform.rows(
            conn.get(conn.platform.path("branches", project=project), params=params)
        )
        branches = [norm_branch(r) for r in rows][: max(1, int(limit))]
        return {"project": s(project), "total": len(branches), "branches": branches}
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "project": s(project)}


def norm_protection(r: dict) -> dict:
    """Normalise one branch-protection row across GitLab / Gitea field names."""
    return {
        "branch": s(pick(r, "name", "branch_name", "rule_name")),
        "allowForcePush": bool(pick(r, "allow_force_push", "enable_force_push", default=False)),
        "raw": {k: v for k, v in r.items() if isinstance(k, str)},
    }


def list_protected_branches(conn: Any, project: str) -> dict:
    """[READ] Branch-protection rules for a project."""
    try:
        rows = conn.platform.rows(
            conn.get(conn.platform.path("protected_branches", project=project))
        )
        protections = [norm_protection(r) for r in rows]
        return {"project": s(project), "total": len(protections), "protections": protections}
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "project": s(project)}


def list_releases(conn: Any, project: str, limit: int = 20) -> dict:
    """[READ] Releases for a project, newest first."""
    try:
        params = {"per_page": min(max(1, int(limit)), _MAX_LIST)}
        rows = conn.platform.rows(
            conn.get(conn.platform.path("releases", project=project), params=params)
        )
        releases = [
            {
                "tag": s(pick(r, "tag_name")),
                "name": s(pick(r, "name"), 160),
                "createdAt": s(pick(r, "created_at")),
                "draft": bool(pick(r, "draft", "upcoming_release", default=False)),
                "prerelease": bool(pick(r, "prerelease", default=False)),
            }
            for r in rows
        ][: max(1, int(limit))]
        return {"project": s(project), "total": len(releases), "releases": releases}
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "project": s(project)}

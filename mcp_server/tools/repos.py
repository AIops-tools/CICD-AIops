"""Repo-surface MCP tools — MRs/PRs, branches, protection, releases (read-only)."""

from typing import Optional

from cicd_aiops.governance import governed_tool
from cicd_aiops.ops import repos as ops
from mcp_server._shared import _get_connection, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_merge_requests(
    project: str,
    state: str = "opened",
    limit: int = 50,
    target: Optional[str] = None,
) -> dict:
    """[READ] Merge/pull requests for a project (default: open ones).

    Args:
        project: Project id or full path ('group/project' / 'owner/repo').
        state: opened/open, merged, closed, all (platform word is translated).
        limit: Max rows to return (default 50).
        target: Server target name from config; omit for the default.
    """
    return ops.list_merge_requests(_get_connection(target), project, state=state, limit=limit)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_branches(project: str, limit: int = 100, target: Optional[str] = None) -> dict:
    """[READ] Branches with last-commit date and protected flag.

    Args:
        project: Project id or full path.
        limit: Max rows to return (default 100).
        target: Server target name from config; omit for the default.
    """
    return ops.list_branches(_get_connection(target), project, limit=limit)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_protected_branches(project: str, target: Optional[str] = None) -> dict:
    """[READ] Branch-protection rules for a project (incl. force-push flags).

    Args:
        project: Project id or full path.
        target: Server target name from config; omit for the default.
    """
    return ops.list_protected_branches(_get_connection(target), project)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_releases(project: str, limit: int = 20, target: Optional[str] = None) -> dict:
    """[READ] Releases for a project, newest first.

    Args:
        project: Project id or full path.
        limit: Max rows to return (default 20).
        target: Server target name from config; omit for the default.
    """
    return ops.list_releases(_get_connection(target), project, limit=limit)

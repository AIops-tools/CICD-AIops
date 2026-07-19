"""Project MCP tools — list, detail with storage statistics (read-only)."""

from typing import Optional

from cicd_aiops.governance import governed_tool
from cicd_aiops.ops import projects as ops
from mcp_server._shared import _get_connection, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_projects(
    search: Optional[str] = None,
    limit: int = 50,
    target: Optional[str] = None,
) -> dict:
    """[READ] Projects/repositories the token can see, with storage numbers.

    Returns {projects:[...], returned, limit, truncated}; 'truncated' true means
    the server had more projects than were returned (measured, not guessed).

    Args:
        search: Optional name filter.
        limit: Max rows to return (default 50, max 99).
        target: Server target name from config; omit for the default.
    """
    return ops.list_projects(_get_connection(target), search=search, limit=limit)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def project_detail(project: str, target: Optional[str] = None) -> dict:
    """[READ] One project's detail incl. repo/artifact byte counts.

    Args:
        project: Project id or full path ('group/project' / 'owner/repo').
        target: Server target name from config; omit for the default.
    """
    return ops.project_detail(_get_connection(target), project)

"""Server MCP tools — version, token identity, one-shot overview (read-only)."""

from typing import Optional

from cicd_aiops.governance import governed_tool
from cicd_aiops.ops import overview as overview_ops
from cicd_aiops.ops import server as ops
from mcp_server._shared import _get_connection, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def server_version(target: Optional[str] = None) -> dict:
    """[READ] CI/CD server version and revision.

    Args:
        target: Server target name from config; omit for the default.
    """
    return ops.server_version(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def current_user(target: Optional[str] = None) -> dict:
    """[READ] The token's identity — who the API sees you as (scope probe).

    Args:
        target: Server target name from config; omit for the default.
    """
    return ops.current_user(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def cicd_overview(target: Optional[str] = None) -> dict:
    """[READ] One-shot summary: version, token identity, projects, runners.

    Resilient — a failing sub-call degrades to a partial summary with an
    'errors' list instead of crashing.

    Args:
        target: Server target name from config; omit for the default.
    """
    return overview_ops.cicd_overview(_get_connection(target))

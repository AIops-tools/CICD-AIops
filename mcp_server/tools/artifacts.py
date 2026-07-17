"""Artifact MCP tools — per-project artifact inventory (read-only)."""

from typing import Optional

from cicd_aiops.governance import governed_tool
from cicd_aiops.ops import artifacts as ops
from mcp_server._shared import _get_connection, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_artifacts(project: str, target: Optional[str] = None) -> dict:
    """[READ] A project's artifact inventory: files, sizes, expiry.

    Also reports how many artifacts are past their expiry date but still kept
    (the delete_artifacts candidates).

    Args:
        project: Project id or full path ('group/project' / 'owner/repo').
        target: Server target name from config; omit for the default.
    """
    return ops.list_artifacts(_get_connection(target), project)

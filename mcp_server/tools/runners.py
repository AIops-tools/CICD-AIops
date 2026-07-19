"""Runner MCP tools — fleet list + per-runner detail (read-only).

Runner administration is a GitLab surface; on a Gitea target the platform
registry raises its standard teaching error listing available resources.
"""

from typing import Optional

from cicd_aiops.governance import governed_tool
from cicd_aiops.ops import runners as ops
from mcp_server._shared import _get_connection, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_runners(
    status: Optional[str] = None,
    limit: int = 100,
    target: Optional[str] = None,
) -> dict:
    """[READ] All runners visible to the token, offline/paused first.

    GITLAB ONLY. Gitea has no runner-administration API, so a Gitea target
    raises a teaching error naming the resources that DO exist there. That is
    a platform-capability answer, not a broken tool: do not retry it, and do
    not report the server as unreachable — answer from the pipeline/job
    surface instead.

    Returns {runners:[...], returned, limit, truncated}; rows are sorted
    offline/paused first BEFORE the cut, so the most urgent runners survive.

    Args:
        status: Optional status filter (online, offline, paused, stale).
        limit: Max rows to return (default 100, capped at 99).
        target: Server target name from config; omit for the default.
    """
    return ops.list_runners(_get_connection(target), status=status, limit=limit)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def runner_detail(runner: str, target: Optional[str] = None) -> dict:
    """[READ] One runner's full detail (contacted_at, tags, paused, version).

    GITLAB ONLY — a Gitea target raises the same teaching error as list_runners.

    Args:
        runner: Runner id (from list_runners).
        target: Server target name from config; omit for the default.
    """
    return ops.runner_detail(_get_connection(target), runner)

"""Pipeline MCP tools — list, detail, jobs, trace tail (read-only)."""

from typing import Optional

from cicd_aiops.governance import governed_tool
from cicd_aiops.ops import pipelines as ops
from mcp_server._shared import _get_connection, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def list_pipelines(
    project: str,
    status: Optional[str] = None,
    limit: int = 20,
    target: Optional[str] = None,
) -> dict:
    """[READ] Recent pipelines/runs for a project, newest first.

    Returns {project, pipelines:[...], returned, limit, truncated}. When
    'truncated' is true the server had MORE pipelines than were returned —
    re-run with a higher limit rather than treating the list as complete.
    Truncation is measured (one extra row is fetched), never guessed.

    Args:
        project: Project id or full path ('group/project' / 'owner/repo').
        status: Optional status filter (e.g. failed, success, running, pending).
        limit: Max rows to return (default 20, max 99).
        target: Server target name from config; omit for the default.
    """
    return ops.list_pipelines(_get_connection(target), project, status=status, limit=limit)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def pipeline_detail(project: str, pipeline: str, target: Optional[str] = None) -> dict:
    """[READ] One pipeline/run's full detail.

    Args:
        project: Project id or full path.
        pipeline: Pipeline/run id (from list_pipelines).
        target: Server target name from config; omit for the default.
    """
    return ops.pipeline_detail(_get_connection(target), project, pipeline)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def pipeline_jobs(
    project: str,
    pipeline: str,
    limit: int = 100,
    target: Optional[str] = None,
) -> dict:
    """[READ] Jobs of one pipeline/run with status + failure reason.

    Returns {project, pipeline, jobs:[...], returned, limit, truncated}. When
    'truncated' is true this pipeline had more jobs than were returned.

    Args:
        project: Project id or full path.
        pipeline: Pipeline/run id (from list_pipelines).
        limit: Max job rows to return (default 100).
        target: Server target name from config; omit for the default.
    """
    return ops.pipeline_jobs(_get_connection(target), project, pipeline, limit=limit)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def job_trace_tail(
    project: str,
    job: str,
    tail_lines: int = 60,
    target: Optional[str] = None,
) -> dict:
    """[READ] The tail of one job's log/trace — where the failure explains itself.

    Returns {project, job, trace, totalLines, tailLines, returned, limit,
    truncated, charsTruncated}. 'truncated' true means earlier lines were
    dropped (the trace is only the tail — the FIRST error may be above the
    window, so raise tail_lines before concluding a root cause);
    'charsTruncated' true means the tail itself hit the byte ceiling.

    Args:
        project: Project id or full path.
        job: Job id (from pipeline_jobs).
        tail_lines: How many trailing lines to return (default 60).
        target: Server target name from config; omit for the default.
    """
    return ops.job_trace_tail(_get_connection(target), project, job, tail_lines=tail_lines)

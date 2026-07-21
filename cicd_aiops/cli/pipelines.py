"""``cicd-aiops pipelines`` — list / show / jobs / trace / retry / cancel."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from cicd_aiops.cli._common import (
    DryRunOption,
    TargetOption,
    cli_errors,
    console,
    double_confirm,
    dry_run_preview,
    get_connection,
    print_result,
)

pipelines_app = typer.Typer(
    name="pipelines",
    help="Pipelines/runs: list, detail, jobs, trace tail, and governed retry/cancel.",
    no_args_is_help=True,
)

ProjectArg = Annotated[str, typer.Argument(help="Project id or full path")]


@pipelines_app.command("list")
@cli_errors
def pipelines_list(
    project: ProjectArg,
    status: Annotated[
        str | None, typer.Option("--status", help="Filter: failed, success, running, ...")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max rows")] = 20,
    target: TargetOption = None,
) -> None:
    """List recent pipelines/runs, newest first."""
    from cicd_aiops.ops import pipelines as ops

    conn, _ = get_connection(target)
    print_result(ops.list_pipelines(conn, project, status=status, limit=limit))


@pipelines_app.command("show")
@cli_errors
def pipelines_show(
    project: ProjectArg,
    pipeline: Annotated[str, typer.Argument(help="Pipeline id (from 'pipelines list')")],
    target: TargetOption = None,
) -> None:
    """Show one pipeline's full detail."""
    from cicd_aiops.ops import pipelines as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.pipeline_detail(conn, project, pipeline)))


@pipelines_app.command("jobs")
@cli_errors
def pipelines_jobs(
    project: ProjectArg,
    pipeline: Annotated[str, typer.Argument(help="Pipeline id (from 'pipelines list')")],
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max jobs")] = 100,
    target: TargetOption = None,
) -> None:
    """List one pipeline's jobs with status + failure reason."""
    from cicd_aiops.ops import pipelines as ops

    conn, _ = get_connection(target)
    print_result(ops.pipeline_jobs(conn, project, pipeline, limit=limit))


@pipelines_app.command("trace")
@cli_errors
def pipelines_trace(
    project: ProjectArg,
    job: Annotated[str, typer.Argument(help="Job id (from 'pipelines jobs')")],
    lines: Annotated[int, typer.Option("--lines", "-n", help="Tail lines")] = 60,
    target: TargetOption = None,
) -> None:
    """Show the tail of one job's log/trace."""
    from cicd_aiops.ops import pipelines as ops

    conn, _ = get_connection(target)
    print_result(ops.job_trace_tail(conn, project, job, tail_lines=lines), hint="--lines")


@pipelines_app.command("retry")
@cli_errors
def pipelines_retry(
    project: ProjectArg,
    pipeline: Annotated[str, typer.Argument(help="Pipeline id to retry")],
    target: TargetOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Retry a failed/canceled pipeline (governed write)."""
    from mcp_server.tools import writes as gov

    if dry_run:
        preview = gov.retry_pipeline(
            project=project, pipeline=pipeline, dry_run=True, target=target
        )
        would = preview.get("wouldRetry", {}) if isinstance(preview, dict) else {}
        dry_run_preview(
            preview,
            operation="retry_pipeline",
            api_call=f"POST {would.get('path', 'retry pipeline')}",
            parameters={"project": project, "pipeline": pipeline},
        )
        return
    double_confirm("retry pipeline", f"{project}#{pipeline}")
    console.print_json(
        json.dumps(gov.retry_pipeline(project=project, pipeline=pipeline, target=target))
    )


@pipelines_app.command("cancel")
@cli_errors
def pipelines_cancel(
    project: ProjectArg,
    pipeline: Annotated[str, typer.Argument(help="Pipeline id to cancel")],
    target: TargetOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Cancel a running pipeline (governed write)."""
    from mcp_server.tools import writes as gov

    if dry_run:
        preview = gov.cancel_pipeline(
            project=project, pipeline=pipeline, dry_run=True, target=target
        )
        would = preview.get("wouldCancel", {}) if isinstance(preview, dict) else {}
        dry_run_preview(
            preview,
            operation="cancel_pipeline",
            api_call=f"POST {would.get('path', 'cancel pipeline')}",
            parameters={"project": project, "pipeline": pipeline},
        )
        return
    double_confirm("cancel pipeline", f"{project}#{pipeline}")
    console.print_json(
        json.dumps(gov.cancel_pipeline(project=project, pipeline=pipeline, target=target))
    )

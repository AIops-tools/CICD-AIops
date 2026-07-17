"""``cicd-aiops runners`` — list / show / pause / resume."""

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
    dry_run_print,
    get_connection,
)

runners_app = typer.Typer(
    name="runners",
    help="Runner fleet: list, detail, and governed pause/resume.",
    no_args_is_help=True,
)


@runners_app.command("list")
@cli_errors
def runners_list(
    status: Annotated[
        str | None, typer.Option("--status", help="Filter: online, offline, paused, stale")
    ] = None,
    target: TargetOption = None,
) -> None:
    """List runners, offline/paused first."""
    from cicd_aiops.ops import runners as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.list_runners(conn, status=status)))


@runners_app.command("show")
@cli_errors
def runners_show(
    runner: Annotated[str, typer.Argument(help="Runner id (from 'runners list')")],
    target: TargetOption = None,
) -> None:
    """Show one runner's full detail."""
    from cicd_aiops.ops import runners as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.runner_detail(conn, runner)))


@runners_app.command("pause")
@cli_errors
def runners_pause(
    runner: Annotated[str, typer.Argument(help="Runner id to pause")],
    target: TargetOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Pause a runner (governed write; undo-recorded)."""
    from mcp_server.tools import writes as gov

    if dry_run:
        dry_run_print(operation="pause_runner", api_call="pause runner",
                      parameters={"runner": runner})
        return
    double_confirm("pause runner", runner)
    console.print_json(json.dumps(gov.pause_runner(runner=runner, target=target)))


@runners_app.command("resume")
@cli_errors
def runners_resume(
    runner: Annotated[str, typer.Argument(help="Runner id to resume")],
    target: TargetOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Resume a paused runner (governed write; undo-recorded)."""
    from mcp_server.tools import writes as gov

    if dry_run:
        dry_run_print(operation="resume_runner", api_call="resume runner",
                      parameters={"runner": runner})
        return
    double_confirm("resume runner", runner)
    console.print_json(json.dumps(gov.resume_runner(runner=runner, target=target)))

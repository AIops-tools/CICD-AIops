"""``cicd-aiops artifacts`` — list / delete (governed, high risk)."""

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

artifacts_app = typer.Typer(
    name="artifacts",
    help="Artifact inventory and governed deletion (high risk).",
    no_args_is_help=True,
)

ProjectArg = Annotated[str, typer.Argument(help="Project id or full path")]


@artifacts_app.command("list")
@cli_errors
def artifacts_list(
    project: ProjectArg,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max rows")] = 500,
    target: TargetOption = None,
) -> None:
    """List a project's artifacts with sizes and expiry."""
    from cicd_aiops.ops import artifacts as ops

    conn, _ = get_connection(target)
    print_result(ops.list_artifacts(conn, project, limit=limit))


@artifacts_app.command("delete")
@cli_errors
def artifacts_delete(
    project: ProjectArg,
    older_than_days: Annotated[
        float,
        typer.Option("--older-than-days", help="Only artifacts older than N days (0 = all)"),
    ] = 0.0,
    target: TargetOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Delete a project's artifacts (governed write, HIGH risk, irreversible)."""
    from mcp_server.tools import writes as gov

    scope = f"older than {older_than_days:g} days" if older_than_days else "ALL"
    if dry_run:
        preview = gov.delete_artifacts(
            project=project, older_than_days=older_than_days, dry_run=True, target=target
        )
        would = preview.get("wouldDelete", {}) if isinstance(preview, dict) else {}
        dry_run_preview(
            preview,
            operation="delete_artifacts",
            api_call=f"DELETE {would.get('path', 'artifacts')}",
            parameters={
                "project": project,
                "scope": scope,
                "currentCount": would.get("currentCount"),
                "currentBytes": would.get("currentBytes"),
                "expiredButKept": would.get("expiredButKept"),
            },
        )
        return
    double_confirm(f"delete artifacts ({scope})", project)
    console.print_json(
        json.dumps(
            gov.delete_artifacts(
                project=project, older_than_days=older_than_days, target=target
            )
        )
    )

"""``cicd-aiops overview`` / ``projects`` — one-shot server summary + project list."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from cicd_aiops.cli._common import TargetOption, cli_errors, console, get_connection


@cli_errors
def overview_cmd(target: TargetOption = None) -> None:
    """One-shot summary: version, token identity, projects, runners."""
    from cicd_aiops.ops import overview as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.cicd_overview(conn)))


@cli_errors
def projects_cmd(
    search: Annotated[
        str | None, typer.Option("--search", "-s", help="Filter projects by name")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max rows")] = 50,
    target: TargetOption = None,
) -> None:
    """List projects/repositories with storage numbers."""
    from cicd_aiops.ops import projects as ops

    conn, _ = get_connection(target)
    console.print_json(json.dumps(ops.list_projects(conn, search=search, limit=limit)))

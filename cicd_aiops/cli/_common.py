"""Shared helpers for cicd-aiops CLI sub-modules."""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console

console = Console()

# ─── Shared Option types ───────────────────────────────────────────────────

TargetOption = Annotated[
    str | None, typer.Option("--target", "-t", help="Target name from config")
]
DryRunOption = Annotated[
    bool, typer.Option("--dry-run", help="Print the API call without executing")
]


def _cli_error_types() -> tuple[type[BaseException], ...]:
    """Exceptions translated to a one-line teaching error instead of a traceback."""
    from cicd_aiops.connection import CicdApiError

    return (CicdApiError, KeyError, OSError, ValueError)


def cli_errors(fn: Callable) -> Callable:
    """Translate known exceptions into one red line + exit code 1."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (typer.Exit, typer.Abort):
            raise
        except _cli_error_types() as e:
            message = str(e)
            if isinstance(e, KeyError):
                message = f"Missing required key or environment variable: {message}"
            console.print(f"[red]Error: {message}[/]")
            raise typer.Exit(1) from e

    return wrapper


def get_connection(target: str | None, config_path: Path | None = None) -> tuple[Any, Any]:
    """Return a (conn, config) tuple for the given target."""
    from cicd_aiops.config import load_config
    from cicd_aiops.connection import ConnectionManager

    cfg = load_config(config_path)
    mgr = ConnectionManager(cfg)
    return mgr.connect(target), cfg


def print_result(result: Any, hint: str = "--limit") -> None:
    """Print a result payload as JSON, then say plainly when it was cut short.

    The ``truncated`` flag is in the payload either way, but a reader — human
    or model — skimming a long JSON dump will miss it. One trailing line costs
    nothing and turns "this looks like everything" into "there is more".
    ``truncated`` is a bool on listings and a per-list dict on the analyses.
    """
    console.print_json(json.dumps(result))
    if not isinstance(result, dict):
        return
    flag = result.get("truncated")
    cut: list[str] = []
    if flag is True:
        cut = ["results"]
    elif isinstance(flag, dict):
        cut = [k for k, v in flag.items() if v]
    if result.get("jobScanTruncated"):
        cut.append("the job scan the inventory was built from")
    if result.get("charsTruncated"):
        cut.append("the trace text (byte ceiling)")
    if cut:
        console.print(
            f"[yellow]… truncated ({', '.join(cut)}) — this is NOT the full set; "
            f"re-run with a higher {hint}.[/]"
        )


def dry_run_print(*, operation: str, api_call: str, parameters: dict | None = None) -> None:
    """Print a dry-run preview of the API call that would be made."""
    console.print("\n[bold magenta][DRY-RUN] No changes will be made.[/]")
    console.print(f"[magenta]  Operation: {operation}[/]")
    console.print(f"[magenta]  API Call:  {api_call}[/]")
    for k, v in (parameters or {}).items():
        console.print(f"[magenta]  Param:     {k} = {v}[/]")
    console.print("[magenta]  Run without --dry-run to execute.[/]\n")


def double_confirm(action: str, resource: str) -> None:
    """Require two confirmations for a destructive operation."""
    console.print(f"[bold yellow]⚠️  About to: {action} '{resource}'[/]")
    typer.confirm(f"Confirm 1/2: {action} '{resource}'?", abort=True)
    typer.confirm(
        f"Confirm 2/2: really {action} '{resource}'? This may be irreversible.",
        abort=True,
    )

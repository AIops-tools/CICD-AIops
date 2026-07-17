"""Top-level Typer app: assembles sub-apps and top-level commands."""

from __future__ import annotations

import typer

from cicd_aiops.cli._common import cli_errors
from cicd_aiops.cli.artifacts import artifacts_app
from cicd_aiops.cli.doctor import doctor_cmd
from cicd_aiops.cli.init import init_cmd
from cicd_aiops.cli.overview import overview_cmd, projects_cmd
from cicd_aiops.cli.pipelines import pipelines_app
from cicd_aiops.cli.rca import rca_app
from cicd_aiops.cli.runners import runners_app
from cicd_aiops.cli.secret import secret_app
from cicd_aiops.cli.undo import undo_app

app = typer.Typer(
    name="cicd-aiops",
    help="Governed AI-ops for self-managed GitLab + Gitea: pipelines, runners, "
    "artifacts, repo hygiene, flagship RCAs, and governed writes "
    "(retry/cancel, pause/resume, artifact deletion, branch protection).",
    no_args_is_help=True,
)

app.add_typer(pipelines_app, name="pipelines")
app.add_typer(runners_app, name="runners")
app.add_typer(artifacts_app, name="artifacts")
app.add_typer(rca_app, name="rca")
app.add_typer(secret_app, name="secret")
app.add_typer(undo_app, name="undo")
app.command("init")(init_cmd)
app.command("overview")(overview_cmd)
app.command("projects")(projects_cmd)
app.command("doctor")(doctor_cmd)


@app.command("mcp")
@cli_errors
def mcp_cmd() -> None:
    """Start the MCP server (stdio transport).

    Single-command entry point for MCP clients (does not go through uvx/PyPI
    resolution at launch):
        cicd-aiops mcp
    """
    import sys

    if sys.version_info < (3, 11):
        typer.echo(
            f"ERROR: cicd-aiops requires Python >= 3.11 "
            f"(got {sys.version_info.major}.{sys.version_info.minor}).\n"
            f"Fix: uv python install 3.12 && "
            f"uv tool install --python 3.12 --force cicd-aiops",
            err=True,
        )
        raise typer.Exit(2)

    from mcp_server.server import main as _mcp_main

    _mcp_main()


if __name__ == "__main__":
    app()

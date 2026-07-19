"""``cicd-aiops rca`` — the four flagship analyses from the terminal."""

from __future__ import annotations

from typing import Annotated

import typer

from cicd_aiops.cli._common import (
    TargetOption,
    cli_errors,
    get_connection,
    print_result,
)

rca_app = typer.Typer(
    name="rca",
    help="Flagship analyses: pipeline failures, runner health, storage bloat, "
    "stale work.",
    no_args_is_help=True,
)

ProjectArg = Annotated[str, typer.Argument(help="Project id or full path")]


@rca_app.command("pipelines")
@cli_errors
def rca_pipelines(
    project: ProjectArg,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Failed pipelines to pull")] = 10,
    target: TargetOption = None,
) -> None:
    """Classify recent failed pipelines: cause + action per pipeline."""
    from cicd_aiops.ops import analysis as ops

    conn, _ = get_connection(target)
    pulled = ops.pull_failed_pipelines(conn, project, limit=limit)
    print_result(ops.pipeline_failure_rca(pulled))


@rca_app.command("runners")
@cli_errors
def rca_runners(target: TargetOption = None) -> None:
    """Flag offline/stale/paused runners and tag saturation."""
    from cicd_aiops.ops import analysis as ops
    from cicd_aiops.ops import runners as runner_ops

    conn, _ = get_connection(target)
    print_result(ops.runner_health_rca(runner_ops.pull_runners(conn)))


@rca_app.command("storage")
@cli_errors
def rca_storage(
    old_days: Annotated[
        float, typer.Option("--old-days", help="Artifact age (days) counted reclaimable")
    ] = 30.0,
    target: TargetOption = None,
) -> None:
    """Rank projects by storage; estimate reclaimable artifact bytes."""
    from cicd_aiops.ops import analysis as ops
    from cicd_aiops.ops import projects as project_ops

    conn, _ = get_connection(target)
    projects = project_ops.pull_projects_with_stats(conn)
    print_result(ops.artifact_storage_bloat_analysis(projects, old_artifact_days=old_days))


@rca_app.command("stale")
@cli_errors
def rca_stale(
    project: ProjectArg,
    mr_days: Annotated[float, typer.Option("--mr-days", help="Open-MR idle threshold")] = 14.0,
    branch_days: Annotated[
        float, typer.Option("--branch-days", help="Branch idle threshold")
    ] = 90.0,
    target: TargetOption = None,
) -> None:
    """Audit long-open MRs/PRs, inactive branches, protection gaps."""
    from cicd_aiops.ops import analysis as ops
    from cicd_aiops.ops import projects as project_ops
    from cicd_aiops.ops import repos as repo_ops

    conn, _ = get_connection(target)
    mrs = repo_ops.list_merge_requests(conn, project).get("mergeRequests", [])
    branches = repo_ops.list_branches(conn, project).get("branches", [])
    protections = repo_ops.list_protected_branches(conn, project).get("protections", [])
    detail = project_ops.project_detail(conn, project)
    print_result(
        ops.stale_work_audit(
            mrs,
            branches,
            protections=protections,
            default_branch=detail.get("defaultBranch") or "",
            stale_mr_days=mr_days,
            stale_branch_days=branch_days,
        )
    )

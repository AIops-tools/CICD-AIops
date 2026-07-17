"""Smoke tests for cicd-aiops.

Proves: every module imports, the CLI builds and --help works, the MCP server
exposes the expected tool surface and EVERY tool carries the harness marker
``_is_governed_tool``, and config platform validation works. No real
GitLab/Gitea is needed.
"""

import asyncio
import importlib

import pytest
from typer.testing import CliRunner

# Kept in sync with mcp_server/server.py (the full registered tool surface).
EXPECTED_TOOLS = {
    # system
    "server_version", "current_user", "cicd_overview",
    # projects
    "list_projects", "project_detail",
    # pipelines
    "list_pipelines", "pipeline_detail", "pipeline_jobs", "job_trace_tail",
    # runners
    "list_runners", "runner_detail",
    # repo surface
    "list_merge_requests", "list_branches", "list_protected_branches",
    "list_releases",
    # artifacts
    "list_artifacts",
    # analysis (flagship)
    "pipeline_failure_rca", "runner_health_rca",
    "artifact_storage_bloat_analysis", "stale_work_audit",
    # writes
    "retry_pipeline", "cancel_pipeline", "pause_runner", "resume_runner",
    "delete_artifacts", "update_branch_protection",
}


@pytest.mark.unit
def test_all_modules_import():
    for name in (
        "cicd_aiops", "cicd_aiops.config", "cicd_aiops.connection",
        "cicd_aiops.platform", "cicd_aiops.doctor",
        "cicd_aiops.secretstore",
        "cicd_aiops.ops.server", "cicd_aiops.ops.projects",
        "cicd_aiops.ops.pipelines", "cicd_aiops.ops.runners",
        "cicd_aiops.ops.repos", "cicd_aiops.ops.artifacts",
        "cicd_aiops.ops.analysis",
        "cicd_aiops.ops.writes", "cicd_aiops.ops.overview",
        "cicd_aiops.cli", "cicd_aiops.cli._root", "cicd_aiops.cli._common",
        "cicd_aiops.cli.init", "cicd_aiops.cli.secret",
        "cicd_aiops.cli.pipelines", "cicd_aiops.cli.runners",
        "cicd_aiops.cli.artifacts", "cicd_aiops.cli.rca",
        "cicd_aiops.cli.overview", "cicd_aiops.cli.doctor",
        "mcp_server.server", "mcp_server._shared",
        "mcp_server.tools.system", "mcp_server.tools.writes",
    ):
        importlib.import_module(name)


@pytest.mark.unit
def test_version_matches_pyproject():
    """__version__ is single-sourced from package metadata; it must track
    pyproject.toml so a release bump can never ship a stale self-report."""
    import tomllib
    from pathlib import Path

    import cicd_aiops

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text("utf-8"))["project"]["version"]
    assert cicd_aiops.__version__ == expected


@pytest.mark.unit
def test_cli_app_builds_and_help_works():
    from cicd_aiops.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for sub in ("pipelines", "runners", "artifacts", "rca", "secret", "init",
                "overview", "projects", "doctor", "mcp"):
        assert sub in result.output


@pytest.mark.unit
def test_cli_leaf_help_triggers_lazy_imports():
    from cicd_aiops.cli import app

    runner = CliRunner()
    for cmd in (
        ["pipelines", "--help"], ["runners", "--help"], ["artifacts", "--help"],
        ["rca", "--help"], ["secret", "--help"], ["doctor", "--help"],
        ["overview", "--help"], ["projects", "--help"], ["init", "--help"],
        ["pipelines", "list", "--help"], ["pipelines", "show", "--help"],
        ["pipelines", "jobs", "--help"], ["pipelines", "trace", "--help"],
        ["pipelines", "retry", "--help"], ["pipelines", "cancel", "--help"],
        ["runners", "list", "--help"], ["runners", "pause", "--help"],
        ["runners", "resume", "--help"],
        ["artifacts", "list", "--help"], ["artifacts", "delete", "--help"],
        ["rca", "pipelines", "--help"], ["rca", "runners", "--help"],
        ["rca", "storage", "--help"], ["rca", "stale", "--help"],
        ["secret", "list", "--help"], ["secret", "set", "--help"],
    ):
        result = runner.invoke(app, cmd)
        assert result.exit_code == 0, f"{cmd} failed: {result.output}"


@pytest.mark.unit
def test_mcp_list_tools_exposes_expected_tools():
    from mcp_server.server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS <= names, f"missing: {EXPECTED_TOOLS - names}"


@pytest.mark.unit
def test_every_mcp_tool_is_governed_by_harness():
    from mcp_server import _shared

    tool_objs = _shared.mcp._tool_manager._tools
    assert EXPECTED_TOOLS <= set(tool_objs), "tool registry incomplete"
    for name, tool in tool_objs.items():
        fn = getattr(tool, "fn", None)
        assert fn is not None, f"{name} has no fn"
        assert getattr(fn, "_is_governed_tool", False), f"{name} missing @governed_tool"


@pytest.mark.unit
def test_tool_count_is_expected():
    from mcp_server import _shared

    assert len(_shared.mcp._tool_manager._tools) == 28


@pytest.mark.unit
def test_read_tools_are_low_risk():
    from mcp_server.tools import analysis, pipelines, projects, repos, runners, system

    for fn in (
        system.server_version, system.current_user, system.cicd_overview,
        projects.list_projects, projects.project_detail,
        pipelines.list_pipelines, pipelines.pipeline_detail,
        pipelines.pipeline_jobs, pipelines.job_trace_tail,
        runners.list_runners, runners.runner_detail,
        repos.list_merge_requests, repos.list_branches,
        repos.list_protected_branches, repos.list_releases,
        analysis.pipeline_failure_rca, analysis.runner_health_rca,
        analysis.artifact_storage_bloat_analysis, analysis.stale_work_audit,
    ):
        assert fn._risk_level == "low", f"{fn.__name__} should be low risk"

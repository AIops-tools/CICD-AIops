"""MCP analysis-tool tests: the live-pull branches and the argument-validation
guards of the four flagship RCA tools.

The pure heuristics are covered in ``test_analysis.py``; here we drive the MCP
wrappers so their "pull live when rows are not injected" path runs. Every live
pull is monkeypatched (no real connection), and the missing-argument guards are
verified to surface through the ``tool_errors`` envelope, not to raise.
"""

from __future__ import annotations

import pytest

import mcp_server.tools.analysis as t


@pytest.fixture
def _no_conn(monkeypatch):
    monkeypatch.setattr(t, "_get_connection", lambda target=None: object())


# ── pipeline_failure_rca ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_pipeline_failure_rca_pulls_live_when_not_injected(monkeypatch, _no_conn):
    def _pull(conn, project, limit, tail_lines):
        assert project == "grp%2Fapi" or project == "grp/api"
        return [
            {
                "id": "5",
                "ref": "main",
                "jobs": [
                    {"name": "unit", "stage": "test", "status": "failed",
                     "traceTail": "AssertionError: boom"},
                ],
            }
        ]

    monkeypatch.setattr(t.ops, "pull_failed_pipelines", _pull)
    out = t.pipeline_failure_rca(project="grp/api")
    assert out["pipelinesEvaluated"] == 1
    assert out["pipelines"][0]["headlineClass"] == "test-failure"


@pytest.mark.unit
def test_pipeline_failure_rca_requires_project_or_rows():
    out = t.pipeline_failure_rca()
    assert "error" in out and "failed_pipelines" in out["error"]


# ── runner_health_rca ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_runner_health_rca_returns_analysis_for_injected_rows():
    out = t.runner_health_rca(
        runners=[{"id": "1", "description": "dead", "status": "offline",
                  "online": False, "paused": False}],
    )
    assert out["runnersEvaluated"] == 1
    assert out["flaggedRunners"][0]["online"] is False


@pytest.mark.unit
def test_runner_health_rca_live_pull_works(monkeypatch, _no_conn):
    """The live-pull branch dispatches to ``ops.runners.pull_runners`` (fixed
    from a wrong ``ops.analysis.pull_runners`` reference)."""
    from cicd_aiops.ops import runners as runner_ops

    monkeypatch.setattr(
        runner_ops,
        "pull_runners",
        lambda conn: [{"id": 1, "description": "r1", "status": "online",
                       "online": True, "paused": False, "tags": ["docker"]}],
    )
    out = t.runner_health_rca()
    assert "error" not in out
    assert out["runnersEvaluated"] == 1


# ── artifact_storage_bloat_analysis ──────────────────────────────────────────


@pytest.mark.unit
def test_bloat_analysis_pulls_projects_live(monkeypatch, _no_conn):
    from cicd_aiops.ops import projects as project_ops

    monkeypatch.setattr(
        project_ops,
        "pull_projects_with_stats",
        lambda conn, limit: [{"path": "dev/api", "repoBytes": 1000, "artifactsBytes": 500}],
    )
    out = t.artifact_storage_bloat_analysis()
    assert out["projectsEvaluated"] == 1
    assert out["projects"][0]["totalBytes"] == 1500


# ── stale_work_audit ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_stale_work_audit_pulls_repo_surface_live(monkeypatch, _no_conn):
    from cicd_aiops.ops import projects as project_ops
    from cicd_aiops.ops import repos as repo_ops

    monkeypatch.setattr(
        repo_ops,
        "list_merge_requests",
        lambda conn, project: {"mergeRequests": [
            {"id": "3", "title": "old", "state": "opened",
             "updatedAt": "2020-01-01T00:00:00Z"},
        ]},
    )
    monkeypatch.setattr(
        repo_ops,
        "list_branches",
        lambda conn, project: {"branches": [
            {"name": "main", "default": True, "protected": False},
        ]},
    )
    monkeypatch.setattr(
        repo_ops, "list_protected_branches", lambda conn, project: {"protections": []}
    )
    monkeypatch.setattr(
        project_ops, "project_detail", lambda conn, project: {"defaultBranch": "main"}
    )

    out = t.stale_work_audit(project="dev/api")
    # the ancient MR is flagged, and the unprotected default branch is a gap
    assert out["counts"]["staleMergeRequests"] == 1
    assert any(g["gap"] == "default-branch-unprotected" for g in out["protectionGaps"])


@pytest.mark.unit
def test_stale_work_audit_requires_project_or_rows():
    out = t.stale_work_audit()
    assert "error" in out and "merge_requests" in out["error"]


@pytest.mark.unit
def test_analysis_tools_are_low_risk():
    for fn in (t.pipeline_failure_rca, t.runner_health_rca,
               t.artifact_storage_bloat_analysis, t.stale_work_audit):
        assert fn._risk_level == "low"

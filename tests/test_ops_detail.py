"""Ops detail reads, partial-error branches, and the ``_util`` field helpers.

``test_reads.py`` covers the happy list paths; this file covers the per-object
detail reads (runner/project/pipeline), the Gitea "surface not available"
teaching re-raise, the resilient ``{"error": ...}`` partial returns when a
transport call blows up, and the shared coercion helpers (``to_bool``, ``num``,
``parse_ts``, ``age_seconds``).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cicd_aiops.config import TargetConfig
from cicd_aiops.ops import (
    artifacts,
    overview,
    pipelines,
    projects,
    repos,
    runners,
    server,
)
from cicd_aiops.platform import GITEA, GITLAB


class _Conn:
    """Fake connection returning canned JSON by path (like test_reads)."""

    def __init__(self, responses, platform=GITLAB):
        self.target = TargetConfig(name="t", platform=platform, base_url="https://h")
        self.platform = self.target.platform_obj
        self._responses = responses

    def get(self, path, **_kw):
        return self._responses.get(path, {})


class _RaisingConn:
    """Fake connection whose every GET raises — drives the partial-error paths."""

    def __init__(self, platform=GITLAB, exc=None):
        self.target = TargetConfig(name="t", platform=platform, base_url="https://h")
        self.platform = self.target.platform_obj
        self._exc = exc or RuntimeError("boom")

    def get(self, path, **_kw):
        raise self._exc


def _p(platform, resource, **fmt):
    from cicd_aiops.platform import get_platform

    return get_platform(platform).path(resource, **fmt)


# ── runner detail ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_runner_detail_normalizes_and_adds_arch_version():
    conn = _Conn({
        _p(GITLAB, "runner", runner="7"): {
            "id": 7, "description": "builder", "status": "online", "online": True,
            "paused": False, "tag_list": ["x86"], "contacted_at": "2026-07-01T00:00:00Z",
            "architecture": "amd64", "version": "16.11.0",
        }
    })
    out = runners.runner_detail(conn, "7")
    assert out["id"] == "7" and out["architecture"] == "amd64"
    assert out["version"] == "16.11.0" and out["tags"] == ["x86"]


@pytest.mark.unit
def test_runner_detail_on_gitea_reraises_teaching_error():
    conn = _Conn({}, platform=GITEA)
    with pytest.raises(KeyError, match="not available on platform 'gitea'"):
        runners.runner_detail(conn, "7")


@pytest.mark.unit
def test_runner_detail_transport_failure_is_partial_error():
    out = runners.runner_detail(_RaisingConn(), "7")
    assert "error" in out and out["runner"] == "7"


@pytest.mark.unit
def test_list_runners_passes_status_filter_and_partial_error():
    conn = _Conn({_p(GITLAB, "runners"): [
        {"id": 1, "status": "online", "online": True, "paused": False},
    ]})
    ok = runners.list_runners(conn, status="Online")
    assert ok["total"] == 1
    assert "error" in runners.list_runners(_RaisingConn())


@pytest.mark.unit
def test_pull_runners_returns_rows_and_empty_on_error():
    conn = _Conn({_p(GITLAB, "runners"): [
        {"id": 1, "status": "online", "online": True, "paused": False},
    ]})
    assert len(runners.pull_runners(conn)) == 1
    assert runners.pull_runners(_RaisingConn()) == []


# ── project detail ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_project_detail_gitlab_with_statistics():
    conn = _Conn({_p(GITLAB, "project", project="grp/api"): {
        "id": 1, "path_with_namespace": "grp/api", "default_branch": "main",
        "statistics": {"repository_size": 2000, "job_artifacts_size": 300},
    }})
    out = projects.project_detail(conn, "grp/api")
    assert out["project"] == "grp/api" and out["repoBytes"] == 2000
    assert out["artifactsBytes"] == 300


@pytest.mark.unit
def test_project_detail_transport_failure_is_partial_error():
    out = projects.project_detail(_RaisingConn(), "grp/api")
    assert "error" in out and out["project"] == "grp/api"


@pytest.mark.unit
def test_list_projects_search_param_and_gitea_size():
    gl = _Conn({_p(GITLAB, "projects"): [
        {"id": 1, "path_with_namespace": "dev/api"},
    ]})
    assert projects.list_projects(gl, search="api")["total"] == 1
    gt = _Conn(
        {_p(GITEA, "projects"): {"data": [{"id": 2, "full_name": "dev/web", "size": 4}]}},
        platform=GITEA,
    )
    out = projects.list_projects(gt, search="web")
    assert out["projects"][0]["repoBytes"] == 4096  # KiB → bytes


@pytest.mark.unit
def test_list_projects_partial_error_and_pull_helper():
    assert "error" in projects.list_projects(_RaisingConn())
    assert projects.pull_projects_with_stats(_RaisingConn()) == []


# ── pipeline detail + partial errors ─────────────────────────────────────────


@pytest.mark.unit
def test_pipeline_detail_normalizes():
    conn = _Conn({_p(GITLAB, "pipeline", project="1", pipeline="9"): {
        "id": 9, "status": "success", "ref": "main", "sha": "abc",
    }})
    out = pipelines.pipeline_detail(conn, "1", "9")
    assert out["id"] == "9" and out["status"] == "success" and out["project"] == "1"


@pytest.mark.unit
def test_list_pipelines_status_filter_and_all_partial_errors():
    conn = _Conn({_p(GITLAB, "pipelines", project="1"): [
        {"id": 1, "status": "failed", "ref": "main"},
    ]})
    assert pipelines.list_pipelines(conn, "1", status="failed")["total"] == 1
    rc = _RaisingConn()
    assert "error" in pipelines.list_pipelines(rc, "1")
    assert "error" in pipelines.pipeline_detail(rc, "1", "9")
    assert "error" in pipelines.pipeline_jobs(rc, "1", "9")
    assert "error" in pipelines.job_trace_tail(rc, "1", "9")


# ── repo-surface partial errors ──────────────────────────────────────────────


@pytest.mark.unit
def test_repo_surface_partial_errors():
    rc = _RaisingConn()
    assert "error" in repos.list_merge_requests(rc, "1")
    assert "error" in repos.list_branches(rc, "1")
    assert "error" in repos.list_protected_branches(rc, "1")
    assert "error" in repos.list_releases(rc, "1")


# ── artifacts: non-dict file skip, partial error, pull helper ────────────────


@pytest.mark.unit
def test_list_artifacts_skips_non_dict_files():
    conn = _Conn({_p(GITLAB, "jobs", project="1"): [
        {"id": 100, "name": "build",
         "artifacts": [{"filename": "app.zip", "size": 10}, "junk-string"],
         "finished_at": "2026-07-01T00:00:00Z"},
    ]})
    out = artifacts.list_artifacts(conn, "1")
    assert out["total"] == 1 and out["totalBytes"] == 10  # the string is ignored


@pytest.mark.unit
def test_list_artifacts_partial_error_and_pull_helper():
    assert "error" in artifacts.list_artifacts(_RaisingConn(), "1")
    assert artifacts.pull_artifacts(_RaisingConn(), "1") == []


# ── overview degrades every failing sub-call to the errors list ──────────────


@pytest.mark.unit
def test_overview_collects_all_subcall_errors():
    out = overview.cicd_overview(_RaisingConn())
    assert out["platform"] == "gitlab"
    joined = " ".join(out["errors"])
    assert "version:" in joined and "user:" in joined
    assert "projects:" in joined and "runners:" in joined
    assert out["version"] is None and out["projectsTotal"] is None


# ── server reads partial errors ──────────────────────────────────────────────


@pytest.mark.unit
def test_server_reads_partial_errors():
    rc = _RaisingConn()
    assert "error" in server.server_version(rc)
    assert "error" in server.current_user(rc)


# ── _util coercion helpers ───────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "value,expected",
    [
        (True, True), (False, False), (1, True), (0, False), (2.5, True),
        ("yes", True), ("Online", True), ("enabled", True),
        ("no", False), ("offline", False), ("", False), ("none", False),
        ("weird-truthy", True),  # unknown non-empty string → truthy fallback
    ],
)
def test_to_bool_coercions(value, expected):
    from cicd_aiops.ops._util import to_bool

    assert to_bool(value) is expected


@pytest.mark.unit
def test_num_coerces_and_defaults_zero():
    from cicd_aiops.ops._util import num

    assert num("12.5") == 12.5
    assert num(None) == 0.0
    assert num("not-a-number") == 0.0


@pytest.mark.unit
def test_parse_ts_handles_naive_and_unparseable():
    from cicd_aiops.ops._util import parse_ts

    assert parse_ts("garbage") is None
    assert parse_ts(None) is None
    naive = parse_ts("2026-07-01T00:00:00")  # no tz → assumed UTC
    assert naive is not None and naive.tzinfo == UTC


@pytest.mark.unit
def test_age_seconds_measures_against_now():
    from cicd_aiops.ops._util import age_seconds

    now = datetime(2026, 7, 1, 0, 5, 0, tzinfo=UTC)
    assert age_seconds("2026-07-01T00:00:00Z", now=now) == pytest.approx(300.0)
    assert age_seconds("garbage") is None

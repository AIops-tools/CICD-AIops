"""Truncation announces itself — and the flag is MEASURED, never guessed.

A cut-off listing that looks complete is the single most damaging failure mode
for a smaller model driving these tools: it reports "that's all the pipelines"
from a page that happened to be full, or — faced with a long job/log feed —
reports that nothing came back at all.

So every listing returns ``{..., "returned": N, "limit": L, "truncated": bool}``
and one row beyond the limit is fetched, so ``truncated`` is a measurement and
not an inference from ``len(rows) == limit``. Where the API returns the complete
set client-side, truncation is measured against that full list instead.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cicd_aiops.cli._root import app
from cicd_aiops.config import TargetConfig
from cicd_aiops.ops import analysis, artifacts, pipelines, projects, repos, runners
from cicd_aiops.platform import GITEA, GITLAB, get_platform

cli = CliRunner()


class _Conn:
    """Fake connection that records the query params it was asked for."""

    def __init__(self, responses, platform=GITLAB):
        self.target = TargetConfig(name="t", platform=platform, base_url="https://h")
        self.platform = self.target.platform_obj
        self._responses = responses
        self.params: dict = {}

    def get(self, path, **kw):
        self.params = kw.get("params") or {}
        return self._responses.get(path, {})


def _p(platform, resource, **fmt):
    return get_platform(platform).path(resource, **fmt)


def _rows(n, **extra):
    return [{"id": i, "status": "failed", **extra} for i in range(n)]


# ── the envelope shape ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_pipeline_listing_over_fetches_one_row_to_measure_truncation():
    conn = _Conn({_p(GITLAB, "pipelines", project="1"): _rows(6)})
    out = pipelines.list_pipelines(conn, "1", limit=5)
    assert conn.params["per_page"] == 6, "one extra row must be requested"
    assert out["returned"] == 5 and out["limit"] == 5
    assert out["truncated"] is True
    assert len(out["pipelines"]) == 5


@pytest.mark.unit
def test_a_full_page_is_not_assumed_to_be_truncated():
    """Exactly `limit` rows available: the old `len == limit` guess said 'more'."""
    conn = _Conn({_p(GITLAB, "pipelines", project="1"): _rows(5)})
    out = pipelines.list_pipelines(conn, "1", limit=5)
    assert out["returned"] == 5
    assert out["truncated"] is False, "measured, not guessed from a full page"


@pytest.mark.unit
def test_short_listing_is_not_truncated():
    conn = _Conn({_p(GITLAB, "pipelines", project="1"): _rows(2)})
    out = pipelines.list_pipelines(conn, "1", limit=20)
    assert out["returned"] == 2 and out["truncated"] is False


@pytest.mark.unit
def test_limit_is_bounded_so_the_extra_row_always_fits_the_page_cap():
    """Both platforms cap a page at 100 rows; asking for 1000 must still measure."""
    conn = _Conn({_p(GITLAB, "pipelines", project="1"): _rows(50)})
    out = pipelines.list_pipelines(conn, "1", limit=1000)
    assert out["limit"] == 99
    assert conn.params["per_page"] == 100, "never exceed the API's page cap"


@pytest.mark.unit
@pytest.mark.parametrize(
    "call, key",
    [
        (lambda c: projects.list_projects(c, limit=2), "projects"),
        (lambda c: repos.list_merge_requests(c, "1", limit=2), "mergeRequests"),
        (lambda c: repos.list_branches(c, "1", limit=2), "branches"),
        (lambda c: repos.list_releases(c, "1", limit=2), "releases"),
        (lambda c: runners.list_runners(c, limit=2), "runners"),
    ],
)
def test_every_listing_carries_the_envelope(call, key):
    conn = _Conn(
        {
            _p(GITLAB, "projects"): _rows(4),
            _p(GITLAB, "merge_requests", project="1"): _rows(4),
            _p(GITLAB, "branches", project="1"): _rows(4),
            _p(GITLAB, "releases", project="1"): _rows(4),
            _p(GITLAB, "runners"): _rows(4),
        }
    )
    out = call(conn)
    assert out["returned"] == 2 and out["limit"] == 2 and out["truncated"] is True
    assert len(out[key]) == 2


@pytest.mark.unit
def test_runner_listing_sorts_before_it_cuts():
    """The offline runner must survive truncation — it is the urgent one."""
    conn = _Conn(
        {
            _p(GITLAB, "runners"): [
                {"id": 1, "online": True, "paused": False},
                {"id": 2, "online": True, "paused": False},
                {"id": 3, "online": False, "paused": False},
            ]
        }
    )
    out = runners.list_runners(conn, limit=1)
    assert out["truncated"] is True
    assert out["runners"][0]["id"] == "3", "offline first, then cut"


# ── client-side (complete-list) truncation ──────────────────────────────────


@pytest.mark.unit
def test_pipeline_jobs_measures_against_the_full_job_list():
    conn = _Conn({_p(GITLAB, "pipeline_jobs", project="1", pipeline="7"): _rows(4)})
    out = pipelines.pipeline_jobs(conn, "1", "7", limit=2)
    assert out["returned"] == 2 and out["truncated"] is True
    out = pipelines.pipeline_jobs(conn, "1", "7", limit=10)
    assert out["returned"] == 4 and out["truncated"] is False


@pytest.mark.unit
def test_protected_branches_carry_the_envelope():
    conn = _Conn({_p(GITLAB, "protected_branches", project="1"): _rows(3, name="main")})
    out = repos.list_protected_branches(conn, "1", limit=1)
    assert out["returned"] == 1 and out["truncated"] is True


@pytest.mark.unit
def test_artifact_inventory_totals_cover_every_row_even_when_cut():
    """Rows may be cut; the byte totals must still describe the whole inventory."""
    conn = _Conn(
        {
            _p(GITEA, "artifacts", project="o/r"): {
                "artifacts": [
                    {"name": f"a{i}.zip", "size_in_bytes": 100} for i in range(5)
                ]
            }
        },
        platform=GITEA,
    )
    out = artifacts.list_artifacts(conn, "o/r", limit=2)
    assert out["returned"] == 2 and out["truncated"] is True
    assert out["artifactsFound"] == 5
    assert out["totalBytes"] == 500, "totals count every artifact, not just the rows"


@pytest.mark.unit
def test_gitlab_artifact_job_scan_reports_its_own_truncation():
    """The GitLab inventory is built from a bounded job scan — say when it was cut."""
    jobs = [
        {"id": i, "name": "build", "artifacts": [{"filename": "a.zip", "size": 1}]}
        for i in range(100)
    ]
    conn = _Conn({_p(GITLAB, "jobs", project="1"): jobs})
    out = artifacts.list_artifacts(conn, "1")
    assert out["jobScanTruncated"] is True
    assert out["jobsScanned"] == 99

    conn = _Conn({_p(GITLAB, "jobs", project="1"): jobs[:5]})
    out = artifacts.list_artifacts(conn, "1")
    assert out["jobScanTruncated"] is False and out["jobsScanned"] == 5


# ── job trace: the highest-value truncation of all ──────────────────────────


@pytest.mark.unit
def test_job_trace_tail_reports_that_earlier_lines_were_dropped():
    trace = "\n".join(f"line {i}" for i in range(200))
    conn = _Conn({_p(GITLAB, "job_trace", project="1", job="5"): trace})
    out = pipelines.job_trace_tail(conn, "1", "5", tail_lines=10)
    assert out["totalLines"] == 200 and out["returned"] == 10
    assert out["truncated"] is True, "the first error may be above the window"
    assert out["charsTruncated"] is False
    assert out["trace"].startswith("line 190")


@pytest.mark.unit
def test_short_trace_is_not_marked_truncated():
    conn = _Conn({_p(GITLAB, "job_trace", project="1", job="5"): "only\ntwo"})
    out = pipelines.job_trace_tail(conn, "1", "5", tail_lines=60)
    assert out["truncated"] is False and out["returned"] == 2


@pytest.mark.unit
def test_job_trace_tail_reports_the_byte_ceiling_separately():
    """A tail short in lines but huge in bytes is still cut — and says so."""
    conn = _Conn({_p(GITLAB, "job_trace", project="1", job="5"): "x" * 20000})
    out = pipelines.job_trace_tail(conn, "1", "5", tail_lines=60)
    assert out["truncated"] is False, "no lines were dropped"
    assert out["charsTruncated"] is True, "but the text was clipped"
    assert len(out["trace"]) == 8000


# ── analyses cap their findings, and say so ─────────────────────────────────


@pytest.mark.unit
def test_analysis_findings_cap_is_measured():
    out = analysis.stale_work_audit(
        [
            {"id": str(i), "state": "opened", "updatedAt": "2020-01-01T00:00:00Z"}
            for i in range(analysis.MAX_ROWS + 5)
        ],
        [],
    )
    assert len(out["staleMergeRequests"]) == analysis.MAX_ROWS
    assert out["truncated"]["staleMergeRequests"] is True
    assert out["truncated"]["staleBranches"] is False
    assert out["counts"]["staleMergeRequests"] == analysis.MAX_ROWS + 5


@pytest.mark.unit
def test_pipeline_rca_reports_its_own_cap():
    rows = [{"id": str(i), "jobs": []} for i in range(analysis.MAX_ROWS + 1)]
    out = analysis.pipeline_failure_rca(rows)
    assert out["pipelinesEvaluated"] == analysis.MAX_ROWS + 1
    assert out["returned"] == analysis.MAX_ROWS and out["truncated"] is True


@pytest.mark.unit
def test_storage_rca_flags_projects_whose_artifact_bytes_are_unknown():
    out = analysis.artifact_storage_bloat_analysis(
        [
            {"path": "o/r", "repoBytes": 10, "artifactsBytes": None},
            {"path": "d/api", "repoBytes": 10, "artifactsBytes": 5},
        ]
    )
    assert out["artifactBytesUnavailable"] == 1
    unknown = next(p for p in out["projects"] if p["project"] == "o/r")
    assert unknown["artifactsBytesKnown"] is False
    assert unknown["artifactsBytes"] is None, "unmeasured, not zero"


# ── undo listing ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_undo_list_measures_truncation():
    from mcp_server.tools import undo as gov

    out = gov.undo_list(limit=5)
    assert out["limit"] == 5 and out["truncated"] is False
    assert out["returned"] == out["count"]


# ── the CLI says it out loud ────────────────────────────────────────────────


@pytest.mark.unit
def test_cli_prints_a_truncation_warning(monkeypatch):
    import cicd_aiops.cli.pipelines as pipe_cli

    conn = _Conn({_p(GITLAB, "pipelines", project="1"): _rows(6)})
    monkeypatch.setattr(pipe_cli, "get_connection", lambda target=None: (conn, object()))

    result = cli.invoke(app, ["pipelines", "list", "1", "--limit", "5"])
    assert result.exit_code == 0, result.output
    assert "truncated" in result.output
    assert "--limit" in result.output, "tell the operator how to get the rest"


@pytest.mark.unit
def test_cli_stays_quiet_when_nothing_was_cut(monkeypatch):
    import cicd_aiops.cli.pipelines as pipe_cli

    conn = _Conn({_p(GITLAB, "pipelines", project="1"): _rows(2)})
    monkeypatch.setattr(pipe_cli, "get_connection", lambda target=None: (conn, object()))

    result = cli.invoke(app, ["pipelines", "list", "1", "--limit", "5"])
    assert result.exit_code == 0
    assert "re-run with a higher" not in result.output

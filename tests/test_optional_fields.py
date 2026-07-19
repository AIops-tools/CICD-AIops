"""Absent fields come back as null, not as an empty string.

An empty string reads as "this field exists and is empty"; a missing field is a
different fact. Collapsing the two hides information from any consumer, and a
smaller local model will confidently invent the difference. These tests pin the
contract end-to-end: helper, ops layer, and the CLI rendering that has to cope
with a null.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cicd_aiops.cli._root import app
from cicd_aiops.config import TargetConfig
from cicd_aiops.governance import opt_str
from cicd_aiops.ops import artifacts, pipelines, projects, repos, runners
from cicd_aiops.platform import GITEA, GITLAB, get_platform

runner = CliRunner()


class _Conn:
    """Fake connection: get() looks up canned responses by path."""

    def __init__(self, responses, platform=GITLAB):
        self.target = TargetConfig(name="t", platform=platform, base_url="https://h")
        self.platform = self.target.platform_obj
        self._responses = responses

    def get(self, path, **_kw):
        return self._responses.get(path, {})


def _p(platform, resource, **fmt):
    return get_platform(platform).path(resource, **fmt)


# ── the helper itself ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_opt_str_distinguishes_absent_from_empty():
    assert opt_str(None) is None, "absent must stay absent"
    assert opt_str("") == "", "a genuinely empty value is not the same as absent"
    assert opt_str("main", 64) == "main"


@pytest.mark.unit
def test_opt_str_still_sanitizes_and_truncates():
    assert opt_str("a\x00b") == "ab"  # control character stripped
    assert opt_str("abcdef", 3) == "abc"


@pytest.mark.unit
def test_opt_str_accepts_non_string_values():
    assert opt_str(42) == "42"


# ── the ops layer ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_pipeline_row_reports_absent_fields_as_none():
    """A pipeline row with no ref/sha/source reports null, not ''."""
    row = pipelines.norm_pipeline({"id": 9, "status": "failed"})
    assert row["id"] == "9" and row["status"] == "failed"
    for key in ("ref", "sha", "source", "createdAt", "updatedAt", "webUrl"):
        assert row[key] is None, f"{key} must stay absent"


@pytest.mark.unit
def test_pipeline_row_keeps_empty_string_when_source_is_empty():
    """An explicitly empty upstream value is preserved as '' — not null."""
    assert pipelines.norm_pipeline({"id": 9, "ref": ""})["ref"] == ""


@pytest.mark.unit
def test_pipeline_row_never_drops_the_key_itself():
    """Keys are always present; only their value may be null."""
    row = pipelines.norm_pipeline({})
    for key in ("id", "status", "ref", "sha", "source", "createdAt", "webUrl"):
        assert key in row, f"{key} must be present even when the source omitted it"


@pytest.mark.unit
def test_job_row_separates_never_started_from_empty():
    """A queued job has no startedAt and a passing job no failureReason."""
    job = pipelines.norm_job({"id": 1, "name": "build", "status": "pending"})
    assert job["startedAt"] is None and job["finishedAt"] is None
    assert job["failureReason"] is None, "'no failure' is not 'an empty reason'"
    assert job["stage"] is None and job["runner"] is None


@pytest.mark.unit
def test_runner_never_contacted_reports_none_not_empty():
    row = runners.norm_runner({"id": 3, "description": "shell-1", "status": "online"})
    assert row["contactedAt"] is None, "never contacted != contacted at ''"
    assert row["runnerType"] is None


@pytest.mark.unit
def test_branch_without_commit_date_reports_none():
    assert repos.norm_branch({"name": "wip"})["lastCommitAt"] is None


@pytest.mark.unit
def test_merge_request_without_author_reports_none():
    mr = repos.norm_merge_request({"iid": 4, "title": "t", "state": "opened"})
    assert mr["author"] is None
    assert mr["sourceBranch"] is None and mr["targetBranch"] is None


@pytest.mark.unit
def test_gitea_project_artifact_bytes_are_null_not_zero():
    """Gitea reports no artifact statistics — that is unmeasured, not zero.

    A 0 here would let a storage RCA state "this project stores no artifacts",
    which is a claim the platform never made.
    """
    conn = _Conn(
        {_p(GITEA, "projects"): {"data": [{"id": 1, "full_name": "o/r", "size": 4}]}},
        platform=GITEA,
    )
    row = projects.list_projects(conn)["projects"][0]
    assert row["artifactsBytes"] is None and row["storageBytes"] is None
    assert row["repoBytes"] == 4096, "repo size IS reported by Gitea"


@pytest.mark.unit
def test_gitlab_project_artifact_bytes_survive_as_numbers():
    conn = _Conn(
        {
            _p(GITLAB, "projects"): [
                {
                    "id": 1,
                    "path_with_namespace": "dev/api",
                    "statistics": {"job_artifacts_size": 0, "storage_size": 7},
                }
            ]
        }
    )
    row = projects.list_projects(conn)["projects"][0]
    assert row["artifactsBytes"] == 0, "a real zero is a measurement, keep it"
    assert row["storageBytes"] == 7


@pytest.mark.unit
def test_artifact_row_without_expiry_reports_none():
    conn = _Conn(
        {
            _p(GITEA, "artifacts", project="o/r"): {
                "artifacts": [{"name": "dist.zip", "size_in_bytes": 10}]
            }
        },
        platform=GITEA,
    )
    row = artifacts.list_artifacts(conn, "o/r")["artifacts"][0]
    assert row["expireAt"] is None, "no expiry policy != expires at ''"
    assert row["createdAt"] is None and row["jobName"] is None


# ── consumers cope with the nulls ───────────────────────────────────────────


@pytest.mark.unit
def test_analysis_handles_null_timestamps():
    """The stale-work audit must not crash on a branch with no commit date."""
    from cicd_aiops.ops import analysis

    out = analysis.stale_work_audit(
        [{"id": "1", "state": "opened", "updatedAt": None, "createdAt": None}],
        [{"name": "wip", "default": False, "protected": False, "lastCommitAt": None}],
    )
    assert out["staleMergeRequests"] == [] and out["staleBranches"] == []


@pytest.mark.unit
def test_runner_rca_handles_null_contact_and_description():
    from cicd_aiops.ops import analysis

    out = analysis.runner_health_rca(
        [{"id": "1", "description": None, "status": "offline",
          "online": False, "paused": False, "contactedAt": None, "tags": []}]
    )
    flagged = out["flaggedRunners"][0]
    assert flagged["description"] is None and flagged["lastContactMin"] is None


@pytest.mark.unit
def test_cli_renders_rows_with_null_fields(monkeypatch):
    """The CLI must survive a null field rather than crashing on render."""
    import cicd_aiops.cli.pipelines as pipe_cli

    conn = _Conn({_p(GITLAB, "pipelines", project="1"): [{"id": 42, "status": "failed"}]})
    monkeypatch.setattr(pipe_cli, "get_connection", lambda target=None: (conn, object()))

    result = runner.invoke(app, ["pipelines", "list", "1"])
    assert result.exit_code == 0, result.output
    assert "42" in result.output
    assert "null" in result.output, "an absent field must render as null, not ''"

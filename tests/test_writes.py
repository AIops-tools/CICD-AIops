"""Unit tests for the governed CI/CD writes (ops + MCP tools).

Proves: every write reads the object's state BEFORE mutating (and the governed
tool records a real undo token where applicable); risk tiers are correct
(delete_artifacts = high, the rest = medium); dry_run previews never mutate;
and the undo descriptors invert correctly and are replayable. No real server —
the connection is a MagicMock.
"""

from unittest.mock import MagicMock

import pytest

from cicd_aiops.platform import GITEA, GITLAB, get_platform


def _conn(platform=GITLAB):
    conn = MagicMock(name="conn")
    conn.target.platform = platform
    conn.platform = get_platform(platform)
    return conn


# ── pipeline retry/cancel prior-status capture ───────────────────────────────


@pytest.mark.unit
def test_retry_pipeline_captures_prior_status_before_posting(monkeypatch):
    from cicd_aiops.ops import pipelines as pipe_ops
    from cicd_aiops.ops import writes as ops

    conn = _conn()
    monkeypatch.setattr(
        pipe_ops, "pipeline_detail", lambda c, p, i: {"id": i, "status": "failed"}
    )
    conn.post.return_value = {"id": 991}

    out = ops.retry_pipeline(conn, "1", "42")

    assert out["priorState"] == {"status": "failed"}
    assert out["newPipeline"] == "991"
    conn.post.assert_called_once()
    assert conn.post.call_args[0][0] == "/api/v4/projects/1/pipelines/42/retry"


@pytest.mark.unit
def test_cancel_pipeline_captures_prior_status(monkeypatch):
    from cicd_aiops.ops import pipelines as pipe_ops
    from cicd_aiops.ops import writes as ops

    conn = _conn()
    monkeypatch.setattr(
        pipe_ops, "pipeline_detail", lambda c, p, i: {"id": i, "status": "running"}
    )
    out = ops.cancel_pipeline(conn, "1", "42")
    assert out["priorState"] == {"status": "running"}
    assert conn.post.call_args[0][0].endswith("/pipelines/42/cancel")


@pytest.mark.unit
def test_pipeline_writes_on_gitea_raise_teaching_error():
    from cicd_aiops.ops import writes as ops

    conn = _conn(GITEA)
    conn.get.return_value = {}
    with pytest.raises(KeyError, match="not available on platform 'gitea'"):
        ops.retry_pipeline(conn, "dev/web", "3")


# ── runner pause/resume prior-state capture ──────────────────────────────────


@pytest.mark.unit
def test_pause_runner_captures_prior_paused_before_mutating(monkeypatch):
    from cicd_aiops.ops import runners as runner_ops
    from cicd_aiops.ops import writes as ops

    conn = _conn()
    monkeypatch.setattr(runner_ops, "runner_detail", lambda c, r: {"id": r, "paused": False})
    out = ops.pause_runner(conn, "7")
    assert out["priorState"] == {"paused": False}
    conn.put.assert_called_once()
    path, kwargs = conn.put.call_args[0][0], conn.put.call_args[1]
    assert path == "/api/v4/runners/7"
    assert kwargs["json"] == {"paused": True}


@pytest.mark.unit
def test_resume_runner_captures_prior_paused(monkeypatch):
    from cicd_aiops.ops import runners as runner_ops
    from cicd_aiops.ops import writes as ops

    conn = _conn()
    monkeypatch.setattr(runner_ops, "runner_detail", lambda c, r: {"id": r, "paused": True})
    out = ops.resume_runner(conn, "7")
    assert out["priorState"] == {"paused": True}
    assert conn.put.call_args[1]["json"] == {"paused": False}


# ── artifact deletion captures bytes/count (priorState, no undo) ─────────────


@pytest.mark.unit
def test_delete_artifacts_bulk_captures_inventory(monkeypatch):
    from cicd_aiops.ops import artifacts as artifact_ops
    from cicd_aiops.ops import writes as ops

    conn = _conn()
    monkeypatch.setattr(
        artifact_ops,
        "list_artifacts",
        lambda c, p: {
            "artifacts": [
                {"jobId": "1", "sizeBytes": 100, "createdAt": "2026-01-01T00:00:00Z"},
                {"jobId": "2", "sizeBytes": 200, "createdAt": "2026-07-16T00:00:00Z"},
            ]
        },
    )
    out = ops.delete_artifacts(conn, "1")
    assert out["priorState"] == {"count": 2, "bytes": 300, "complete": True}
    # bytes is a byte count — an integer quantity, not a float (bug class #2).
    # Equality cannot catch it (300 == 300.0); assert the type explicitly.
    total = out["priorState"]["bytes"]
    assert isinstance(total, int) and not isinstance(total, bool)
    conn.delete.assert_called_once_with("/api/v4/projects/1/artifacts")


@pytest.mark.unit
def test_delete_artifacts_older_than_deletes_per_matching_job(monkeypatch):
    from cicd_aiops.ops import artifacts as artifact_ops
    from cicd_aiops.ops import writes as ops

    conn = _conn()
    monkeypatch.setattr(
        artifact_ops,
        "list_artifacts",
        lambda c, p: {
            "artifacts": [
                {"jobId": "10", "sizeBytes": 500, "createdAt": "2026-01-01T00:00:00Z"},
                {"jobId": "11", "sizeBytes": 700, "createdAt": "2026-07-16T00:00:00Z"},
            ]
        },
    )
    out = ops.delete_artifacts(conn, "1", older_than_days=30)
    # only the January artifact matches → only job 10's artifacts deleted
    assert out["priorState"] == {"count": 1, "bytes": 500, "complete": True}
    conn.delete.assert_called_once_with("/api/v4/projects/1/jobs/10/artifacts")


# ── branch protection captures prior settings ────────────────────────────────


@pytest.mark.unit
def test_update_branch_protection_captures_prior_settings():
    from cicd_aiops.ops import writes as ops

    conn = _conn()
    conn.get.return_value = {"name": "main", "allow_force_push": True}
    out = ops.update_branch_protection(conn, "1", "main", allow_force_push=False)
    assert out["priorState"] == {"protected": True, "allowForcePush": True}
    conn.patch.assert_called_once()  # existing rule → PATCH, not POST
    assert conn.patch.call_args[1]["json"] == {"allow_force_push": False}


@pytest.mark.unit
def test_update_branch_protection_unprotected_prior_is_404():
    from cicd_aiops.connection import CicdApiError
    from cicd_aiops.ops import writes as ops

    conn = _conn()
    conn.get.side_effect = CicdApiError("not found", status_code=404)
    out = ops.update_branch_protection(conn, "1", "main")
    assert out["priorState"] == {"protected": False, "allowForcePush": None}
    conn.post.assert_called_once()  # no rule yet → POST creates one


@pytest.mark.unit
def test_update_branch_protection_gitea_payload():
    from cicd_aiops.connection import CicdApiError
    from cicd_aiops.ops import writes as ops

    conn = _conn(GITEA)
    conn.get.side_effect = CicdApiError("not found", status_code=404)
    ops.update_branch_protection(conn, "dev/web", "main", allow_force_push=False)
    path = conn.post.call_args[0][0]
    assert path == "/api/v1/repos/dev/web/branch_protections"
    assert conn.post.call_args[1]["json"]["branch_name"] == "main"


# ── governed tool records a real undo token ─────────────────────────────────


@pytest.mark.unit
def test_governed_pause_runner_records_undo_token(monkeypatch):
    """End-to-end: the governed pause_runner records an inverse in the undo store."""
    from cicd_aiops.governance.undo import get_undo_store
    from cicd_aiops.ops import runners as runner_ops
    from mcp_server.tools import writes as t

    conn = _conn()
    monkeypatch.setattr(runner_ops, "runner_detail", lambda c, r: {"id": r, "paused": False})
    monkeypatch.setattr(t, "_get_connection", lambda target=None: conn)

    result = t.pause_runner(runner="7")

    assert "_undo_id" in result
    recorded = get_undo_store().list()
    assert any(u.get("undo_tool") == "resume_runner" for u in recorded)


@pytest.mark.unit
def test_governed_pause_of_already_paused_runner_records_no_undo(monkeypatch):
    """Pausing a runner that was already paused must NOT record a 'resume'
    undo — replaying it would flip the runner to a state it never had."""
    from cicd_aiops.governance.undo import get_undo_store
    from cicd_aiops.ops import runners as runner_ops
    from mcp_server.tools import writes as t

    conn = _conn()
    monkeypatch.setattr(runner_ops, "runner_detail", lambda c, r: {"id": r, "paused": True})
    monkeypatch.setattr(t, "_get_connection", lambda target=None: conn)

    result = t.pause_runner(runner="7")
    assert "_undo_id" not in result
    assert not any(u.get("undo_tool") == "resume_runner" for u in get_undo_store().list())


# ── risk tiers ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_write_risk_tiers():
    from mcp_server.tools import writes as t

    assert t.delete_artifacts._risk_level == "high"
    for fn in (t.retry_pipeline, t.cancel_pipeline, t.pause_runner,
               t.resume_runner, t.update_branch_protection):
        assert fn._risk_level == "medium"


# ── dry-run previews never mutate ───────────────────────────────────────────


@pytest.mark.unit
def test_dry_run_previews_do_not_mutate(monkeypatch):
    from mcp_server.tools import writes as t

    conn = _conn()
    conn.get.return_value = {}
    monkeypatch.setattr(t, "_get_connection", lambda target=None: conn)

    assert t.retry_pipeline(project="1", pipeline="42", dry_run=True)["dryRun"] is True
    assert t.cancel_pipeline(project="1", pipeline="42", dry_run=True)["dryRun"] is True
    assert t.pause_runner(runner="7", dry_run=True)["dryRun"] is True
    assert t.resume_runner(runner="7", dry_run=True)["dryRun"] is True
    assert t.update_branch_protection(project="1", branch="main", dry_run=True)[
        "dryRun"] is True
    conn.post.assert_not_called()
    conn.put.assert_not_called()
    conn.patch.assert_not_called()
    conn.delete.assert_not_called()


@pytest.mark.unit
def test_delete_artifacts_dry_run_reports_inventory_without_deleting(monkeypatch):
    from cicd_aiops.ops import artifacts as artifact_ops
    from mcp_server.tools import writes as t

    conn = _conn()
    monkeypatch.setattr(t, "_get_connection", lambda target=None: conn)
    monkeypatch.setattr(
        artifact_ops,
        "list_artifacts",
        lambda c, p: {"total": 3, "totalBytes": 999, "expiredButKept": 2, "artifacts": []},
    )
    out = t.delete_artifacts(project="1", dry_run=True)
    assert out["dryRun"] is True
    assert out["wouldDelete"]["currentBytes"] == 999
    conn.delete.assert_not_called()


# ── undo descriptors invert correctly and are REPLAYABLE ────────────────────


@pytest.mark.unit
def test_runner_undo_descriptors_invert():
    from mcp_server.tools import writes as t

    pause_undo = t._pause_runner_undo({"runner": "7"}, {"priorState": {"paused": False}})
    assert pause_undo["tool"] == "resume_runner"
    assert pause_undo["params"] == {"runner": "7"}
    # already-paused prior → no undo
    assert t._pause_runner_undo({"runner": "7"}, {"priorState": {"paused": True}}) is None

    resume_undo = t._resume_runner_undo({"runner": "7"}, {"priorState": {"paused": True}})
    assert resume_undo["tool"] == "pause_runner"
    assert resume_undo["params"] == {"runner": "7"}
    assert t._resume_runner_undo({"runner": "7"}, {"priorState": {"paused": False}}) is None


@pytest.mark.unit
def test_protection_undo_replays_prior_settings():
    from mcp_server.tools import writes as t

    desc = t._protection_undo(
        {"project": "1", "branch": "main"},
        {"priorState": {"protected": True, "allowForcePush": True}},
    )
    assert desc["tool"] == "update_branch_protection"
    assert desc["params"] == {
        "project": "1", "branch": "main", "protect": True, "allow_force_push": True,
    }
    # previously unprotected → undo removes the protection again
    desc = t._protection_undo(
        {"project": "1", "branch": "main"},
        {"priorState": {"protected": False, "allowForcePush": None}},
    )
    assert desc["params"] == {"project": "1", "branch": "main", "protect": False}


@pytest.mark.unit
def test_undo_descriptors_replay_against_target_tool_signature(monkeypatch):
    """The recorded undo params must be accepted verbatim by the target tool —
    replay the runner and protection undos end-to-end."""
    from cicd_aiops.connection import CicdApiError
    from cicd_aiops.ops import runners as runner_ops
    from mcp_server.tools import writes as t

    conn = _conn()
    conn.get.side_effect = CicdApiError("not found", status_code=404)
    monkeypatch.setattr(runner_ops, "runner_detail", lambda c, r: {"id": r, "paused": True})
    monkeypatch.setattr(t, "_get_connection", lambda target=None: conn)

    pause_undo = t._pause_runner_undo({"runner": "7"}, {"priorState": {"paused": False}})
    replay = t.resume_runner(**pause_undo["params"])
    assert replay["action"] == "resume_runner" and "error" not in replay

    prot_undo = t._protection_undo(
        {"project": "1", "branch": "main"},
        {"priorState": {"protected": False, "allowForcePush": None}},
    )
    replay = t.update_branch_protection(**prot_undo["params"])
    assert replay["action"] == "update_branch_protection" and "error" not in replay

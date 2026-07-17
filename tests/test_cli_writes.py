"""CLI confirmed-write path — past dry-run, through governance, onto disk.

The CLI write commands delegate real execution to the ``@governed_tool``
functions in ``mcp_server.tools``. These tests drive ``runners pause`` PAST the
dry-run branch and the double-confirm prompts and assert the call really went
through the governed path (audit row on disk) — the regression test for the
"CLI writes were unaudited" line-wide fix.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

import cicd_aiops.governance.audit as audit_mod
import cicd_aiops.governance.policy as policy_mod
import cicd_aiops.governance.undo as undo_mod
from cicd_aiops.platform import GITLAB, get_platform


@pytest.fixture
def gov_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICD_AIOPS_HOME", str(tmp_path))
    audit_mod.reset_engine()
    policy_mod.reset_policy_engine()
    undo_mod.reset_undo_store()
    yield tmp_path
    audit_mod.reset_engine()
    policy_mod.reset_policy_engine()
    undo_mod.reset_undo_store()


@pytest.fixture
def gl_conn(monkeypatch):
    """A fake GitLab connection wired into the governed write module."""
    from cicd_aiops.ops import runners as runner_ops
    from mcp_server.tools import writes as gov

    conn = MagicMock(name="conn")
    conn.target.platform = GITLAB
    conn.platform = get_platform(GITLAB)
    monkeypatch.setattr(runner_ops, "runner_detail", lambda c, r: {"id": r, "paused": False})
    monkeypatch.setattr(gov, "_get_connection", lambda target=None: conn)
    return conn


def _audit_tools(db_path) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        return [r[0] for r in conn.execute("SELECT tool FROM audit_log ORDER BY id")]
    finally:
        conn.close()


@pytest.mark.unit
def test_cli_runners_pause_dry_run_makes_no_call_and_no_audit(gov_home, gl_conn):
    from cicd_aiops.cli import app

    result = CliRunner().invoke(app, ["runners", "pause", "7", "--dry-run"])
    assert result.exit_code == 0
    assert "DRY-RUN" in result.output
    gl_conn.put.assert_not_called()
    assert not (gov_home / "audit.db").exists()


@pytest.mark.unit
def test_cli_runners_pause_confirmed_goes_through_governance(gov_home, gl_conn):
    """Confirmed CLI write must execute via the governed twin: the API call
    fires AND an audit row lands in audit.db (this is what the reroute fix
    bought)."""
    from cicd_aiops.cli import app

    result = CliRunner().invoke(app, ["runners", "pause", "7"], input="y\ny\n")
    assert result.exit_code == 0, result.output
    gl_conn.put.assert_called_once()
    assert _audit_tools(gov_home / "audit.db") == ["pause_runner"]


@pytest.mark.unit
def test_cli_runners_pause_aborts_without_double_confirm(gov_home, gl_conn):
    from cicd_aiops.cli import app

    result = CliRunner().invoke(app, ["runners", "pause", "7"], input="y\nn\n")
    assert result.exit_code != 0
    gl_conn.put.assert_not_called()
    assert not (gov_home / "audit.db").exists()


@pytest.mark.unit
def test_cli_artifacts_delete_dry_run_makes_no_call(gov_home, gl_conn):
    from cicd_aiops.cli import app

    result = CliRunner().invoke(
        app, ["artifacts", "delete", "1", "--older-than-days", "30", "--dry-run"]
    )
    assert result.exit_code == 0
    assert "DRY-RUN" in result.output
    gl_conn.delete.assert_not_called()
    assert not (gov_home / "audit.db").exists()


@pytest.mark.unit
def test_cli_pipelines_cancel_confirmed_is_audited(gov_home, gl_conn, monkeypatch):
    from cicd_aiops.cli import app
    from cicd_aiops.ops import pipelines as pipe_ops

    monkeypatch.setattr(
        pipe_ops, "pipeline_detail", lambda c, p, i: {"id": i, "status": "running"}
    )
    result = CliRunner().invoke(app, ["pipelines", "cancel", "1", "42"], input="y\ny\n")
    assert result.exit_code == 0, result.output
    gl_conn.post.assert_called_once()
    assert _audit_tools(gov_home / "audit.db") == ["cancel_pipeline"]

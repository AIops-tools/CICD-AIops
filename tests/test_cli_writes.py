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


def _no_mutating_call(conn) -> None:
    """No POST/PUT/PATCH/DELETE reached the server, whatever else happened."""
    conn.post.assert_not_called()
    conn.put.assert_not_called()
    conn.patch.assert_not_called()
    conn.delete.assert_not_called()


@pytest.mark.unit
def test_cli_runners_pause_dry_run_reads_and_audits_but_never_writes(gov_home, gl_conn):
    """A dry_run MAY read; it must never write.

    The older "dry_run does zero I/O and leaves no trace" assumption was never a
    stated rule and is wrong on its face: a preview that cannot read cannot
    answer "would this be refused?", which is the most valuable thing a preview
    can say. So the read is expected, the audit row is expected (MCP previews
    were always audited — the CLI silently not auditing was the outlier), and
    only the MUTATING call is forbidden.
    """
    from cicd_aiops.cli import app

    result = CliRunner().invoke(app, ["runners", "pause", "7", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "DRY-RUN" in result.output  # human banner preserved, not raw JSON
    _no_mutating_call(gl_conn)
    assert _audit_tools(gov_home / "audit.db") == ["pause_runner"]


@pytest.mark.unit
def test_cli_runners_pause_dry_run_records_no_undo_token(gov_home, gl_conn):
    """A preview changed nothing, so there is nothing to reverse.

    A phantom undo token is not inert: undo_apply would dispatch a REAL
    resume_runner for a pause that never happened.
    """
    from cicd_aiops.cli import app

    CliRunner().invoke(app, ["runners", "pause", "7", "--dry-run"])
    if (gov_home / "undo.db").exists():
        rows = sqlite3.connect(gov_home / "undo.db").execute(
            "SELECT undo_tool FROM undo_log"
        ).fetchall()
        assert rows == [], f"dry-run registered a phantom undo: {rows}"


@pytest.mark.unit
def test_cli_runners_pause_dry_run_on_gitea_refuses_nonzero(gov_home, monkeypatch):
    """Gitea has no runner API — the preview must refuse, not promise a pause.

    This is the whole reason the preview routes through the governed twin: the
    platform registry's teaching error is raised at preview time, so the reader
    is not told "here is what would happen" for a call that cannot happen.
    """
    from cicd_aiops.cli import app
    from cicd_aiops.platform import GITEA, get_platform
    from mcp_server.tools import writes as gov

    conn = MagicMock(name="conn")
    conn.target.platform = GITEA
    conn.platform = get_platform(GITEA)
    monkeypatch.setattr(gov, "_get_connection", lambda target=None: conn)

    result = CliRunner().invoke(app, ["runners", "pause", "7", "--dry-run"])
    assert result.exit_code == 1
    assert "not available on platform 'gitea'" in result.output
    assert "DRY-RUN" not in result.output  # no green banner for a refusal
    # str(KeyError) repr-quotes its message; the flattened-dict path must strip
    # them exactly as cli_errors does on the exception path.
    assert 'Error: "' not in result.output
    _no_mutating_call(conn)


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
def test_cli_artifacts_delete_dry_run_reads_and_audits_but_never_writes(gov_home, gl_conn):
    """A dry_run MAY read; it must never write.

    delete_artifacts is the HIGH tier, and its preview now carries the real
    inventory it read rather than a hand-written string — so the banner reports
    what would actually be destroyed. A preview changes nothing: it reads and
    audits, but never issues the mutating call.
    """
    from cicd_aiops.cli import app

    result = CliRunner().invoke(
        app, ["artifacts", "delete", "1", "--older-than-days", "30", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert "DRY-RUN" in result.output
    _no_mutating_call(gl_conn)
    assert _audit_tools(gov_home / "audit.db") == ["delete_artifacts"]


@pytest.mark.unit
def test_cli_artifacts_delete_dry_run_on_gitea_refuses_nonzero(gov_home, monkeypatch):
    """Gitea has no bulk artifact-deletion API — refuse rather than promise it."""
    from cicd_aiops.cli import app
    from cicd_aiops.platform import GITEA, get_platform
    from mcp_server.tools import writes as gov

    conn = MagicMock(name="conn")
    conn.target.platform = GITEA
    conn.platform = get_platform(GITEA)
    monkeypatch.setattr(gov, "_get_connection", lambda target=None: conn)

    result = CliRunner().invoke(app, ["artifacts", "delete", "o/r", "--dry-run"])
    assert result.exit_code == 1
    assert "not available on platform 'gitea'" in result.output
    assert "DRY-RUN" not in result.output
    _no_mutating_call(conn)


@pytest.mark.unit
def test_cli_pipelines_cancel_dry_run_reads_and_audits_but_never_writes(
    gov_home, gl_conn, monkeypatch
):
    """A dry_run MAY read; it must never write."""
    from cicd_aiops.cli import app

    result = CliRunner().invoke(app, ["pipelines", "cancel", "1", "42", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "DRY-RUN" in result.output
    _no_mutating_call(gl_conn)
    assert _audit_tools(gov_home / "audit.db") == ["cancel_pipeline"]


@pytest.mark.unit
def test_cli_undo_apply_dry_run_of_an_unknown_token_refuses_nonzero(gov_home):
    """An unknown undo id is a refusal, not a preview of 'inverse: ?'.

    Before the reroute this printed a green banner naming the inverse tool as
    '?' — a preview of an operation that does not exist.
    """
    from cicd_aiops.cli import app

    result = CliRunner().invoke(app, ["undo", "apply", "nope-not-a-token", "--dry-run"])
    assert result.exit_code == 1
    assert "Unknown undo id" in result.output
    assert "DRY-RUN" not in result.output


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

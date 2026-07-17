"""``cicd-aiops secret`` CLI tests — the encrypted credential store commands.

The store is redirected at a tmp dir (nothing touches the real
``~/.cicd-aiops``) and the master password is supplied through the
``CICD_AIOPS_MASTER_PASSWORD`` env var so the commands run non-interactively.
A secret value is never printed; these assert the workflow (set → list → rm),
the migrate and rotate-password flows, and that no plaintext leaks to stdout.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

import cicd_aiops.cli.secret as sec
import cicd_aiops.secretstore as ss
from cicd_aiops.cli.secret import secret_app

runner = CliRunner()


@pytest.fixture
def store_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ss, "SECRETS_FILE", tmp_path / "secrets.enc")
    monkeypatch.setattr(ss, "LEGACY_ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(ss, "_cached", None)
    monkeypatch.setenv("CICD_AIOPS_MASTER_PASSWORD", "master-pw")
    return tmp_path


@pytest.mark.unit
def test_set_then_list_shows_name_not_value(store_dir):
    res = runner.invoke(secret_app, ["set", "gl1", "--value", "glpat-secret-xyz"])
    assert res.exit_code == 0
    assert "gl1" in res.stdout
    assert "glpat-secret-xyz" not in res.stdout  # value never printed

    res = runner.invoke(secret_app, ["list"])
    assert res.exit_code == 0
    assert "gl1" in res.stdout
    assert "glpat-secret-xyz" not in res.stdout


@pytest.mark.unit
def test_list_empty_store_hints_how_to_add(store_dir):
    res = runner.invoke(secret_app, ["list"])
    assert res.exit_code == 0
    assert "No secrets stored" in res.stdout


@pytest.mark.unit
def test_set_prompts_hidden_when_value_omitted(store_dir, monkeypatch):
    monkeypatch.setattr(sec.getpass, "getpass", lambda prompt="": "prompted-token")
    res = runner.invoke(secret_app, ["set", "gt1"])
    assert res.exit_code == 0
    assert ss.SecretStore.unlock("master-pw").get("gt1") == "prompted-token"


@pytest.mark.unit
def test_rm_deletes_stored_secret(store_dir):
    runner.invoke(secret_app, ["set", "gl1", "--value", "v"])
    res = runner.invoke(secret_app, ["rm", "gl1"])
    assert res.exit_code == 0
    assert ss.SecretStore.unlock("master-pw").names() == ()


@pytest.mark.unit
def test_migrate_reports_nothing_when_no_legacy_env(store_dir):
    res = runner.invoke(secret_app, ["migrate"])
    assert res.exit_code == 0
    assert "Nothing to migrate" in res.stdout


@pytest.mark.unit
def test_migrate_imports_legacy_env_secrets(store_dir):
    (store_dir / ".env").write_text("CICD_GL1_SECRET=legacy-tok\n# comment\n")
    res = runner.invoke(secret_app, ["migrate"])
    assert res.exit_code == 0
    assert "gl1" in res.stdout
    assert ss.SecretStore.unlock("master-pw").get("gl1") == "legacy-tok"


@pytest.mark.unit
def test_rotate_password_mismatch_aborts(store_dir, monkeypatch):
    runner.invoke(secret_app, ["set", "gl1", "--value", "v"])
    pws = iter(["new-pw", "different-pw"])
    monkeypatch.setattr(sec.getpass, "getpass", lambda prompt="": next(pws))
    res = runner.invoke(secret_app, ["rotate-password"])
    assert res.exit_code == 1
    assert "did not match" in res.stdout


@pytest.mark.unit
def test_rotate_password_reencrypts_under_new_password(store_dir, monkeypatch):
    runner.invoke(secret_app, ["set", "gl1", "--value", "v"])
    pws = iter(["new-pw", "new-pw"])
    monkeypatch.setattr(sec.getpass, "getpass", lambda prompt="": next(pws))
    res = runner.invoke(secret_app, ["rotate-password"])
    assert res.exit_code == 0
    assert ss.SecretStore.unlock("new-pw").get("gl1") == "v"

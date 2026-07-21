"""Test isolation: redirect the governance harness state at a tmp dir.

Governed-tool calls write an audit row (and, for reversible writes, an undo
token). This autouse fixture points ``CICD_AIOPS_HOME`` at a throwaway
directory and resets the harness singletons so nothing touches the real
``~/.cicd-aiops`` during tests.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_harness_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("cicd-home")
    monkeypatch.setenv("CICD_AIOPS_HOME", str(home))

    import cicd_aiops.governance.audit as audit
    import cicd_aiops.governance.undo as undo

    monkeypatch.setattr(audit, "_engine", None, raising=False)
    monkeypatch.setattr(audit, "_DEFAULT_DB", None, raising=False)
    monkeypatch.setattr(undo, "_store", None, raising=False)
    yield


@pytest.fixture(autouse=True)
def _default_approver(monkeypatch):
    """Record a synthetic approver on every audit row so the trail looks
    realistic. The approver is an optional annotation now — it gates nothing —
    but the governance-persistence tests clear it to prove a high-risk write
    still runs without one."""
    monkeypatch.setenv("CICD_AUDIT_APPROVED_BY", "pytest")

"""Connection-layer tests: auth headers, teaching-error translation, HTTP verb
dispatch, and the multi-target ConnectionManager.

No real GitLab/Gitea — an injected fake httpx client records every request and
returns canned responses, so the auth-header selection (GitLab PRIVATE-TOKEN vs
Gitea ``Authorization: token``), the non-2xx → teaching ``CicdApiError``
mapping, and the JSON/plain-text/empty response handling are all exercised
offline.
"""

from __future__ import annotations

import httpx
import pytest

from cicd_aiops.config import TargetConfig
from cicd_aiops.connection import (
    CicdApiError,
    CicdConnection,
    ConnectionManager,
    _teaching_message,
)
from cicd_aiops.platform import GITEA, GITLAB


class _FakeResp:
    def __init__(self, status_code=200, json_data=None, text="", content=b'{"ok": 1}'):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {"ok": 1}
        self.text = text
        self.content = content

    def json(self):
        if self._json_data is _RAISE:
            raise ValueError("not json")
        return self._json_data


_RAISE = object()


class _FakeClient:
    def __init__(self, resp=None, exc=None):
        self._resp = resp if resp is not None else _FakeResp()
        self._exc = exc
        self.calls: list[tuple] = []
        self.closed = False

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if self._exc is not None:
            raise self._exc
        return self._resp

    def close(self):
        self.closed = True


def _target(platform=GITLAB):
    return TargetConfig(name="t1", platform=platform, base_url="https://h")


# ── auth header selection ────────────────────────────────────────────────────


@pytest.mark.unit
def test_gitlab_uses_private_token_header(monkeypatch):
    monkeypatch.setenv("CICD_T1_SECRET", "glpat-xyz")
    headers = CicdConnection._build_headers(_target(GITLAB))
    assert headers["PRIVATE-TOKEN"] == "glpat-xyz"
    assert "Authorization" not in headers


@pytest.mark.unit
def test_gitea_uses_authorization_token_prefix(monkeypatch):
    monkeypatch.setenv("CICD_T1_SECRET", "gitea-abc")
    headers = CicdConnection._build_headers(_target(GITEA))
    assert headers["Authorization"] == "token gitea-abc"
    assert "PRIVATE-TOKEN" not in headers


# ── teaching-error message mapping (every status branch) ─────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "status,needle",
    [
        (401, "Authentication/authorization failed"),
        (403, "Authentication/authorization failed"),
        (404, "Resource not found"),
        (400, "Bad request"),
        (429, "Rate limited"),
        (500, "server error"),
        (503, "server error"),
        (418, "API error (418)"),
    ],
)
def test_teaching_message_per_status(status, needle):
    msg = _teaching_message(status, "/api/v4/projects", "boom body", "GitLab")
    assert needle in msg
    assert "/api/v4/projects" in msg


# ── request dispatch + response handling ─────────────────────────────────────


@pytest.mark.unit
def test_get_returns_parsed_json_and_records_call():
    fake = _FakeClient(_FakeResp(json_data={"version": "17.2"}))
    conn = CicdConnection(_target(GITLAB), client=fake)
    out = conn.get("/api/v4/version", params={"a": 1})
    assert out == {"version": "17.2"}
    method, path, kwargs = fake.calls[0]
    assert method == "GET" and path == "/api/v4/version"
    assert kwargs["params"] == {"a": 1}


@pytest.mark.unit
def test_verbs_map_to_http_methods():
    fake = _FakeClient(_FakeResp(json_data={}))
    conn = CicdConnection(_target(GITLAB), client=fake)
    conn.post("/p")
    conn.put("/p")
    conn.patch("/p")
    conn.delete("/p")
    assert [c[0] for c in fake.calls] == ["POST", "PUT", "PATCH", "DELETE"]


@pytest.mark.unit
def test_empty_body_returns_empty_dict():
    fake = _FakeClient(_FakeResp(status_code=204, content=b""))
    conn = CicdConnection(_target(GITLAB), client=fake)
    assert conn.delete("/api/v4/projects/1/artifacts") == {}


@pytest.mark.unit
def test_non_json_body_passes_through_as_text():
    """Job traces return plain text — a JSON parse failure must pass through."""
    fake = _FakeClient(_FakeResp(json_data=_RAISE, text="line1\nline2", content=b"line1"))
    conn = CicdConnection(_target(GITLAB), client=fake)
    assert conn.get("/api/v4/projects/1/jobs/9/trace") == "line1\nline2"


@pytest.mark.unit
def test_non_2xx_raises_cicd_api_error_with_status():
    fake = _FakeClient(_FakeResp(status_code=404, text="nope", content=b"nope"))
    conn = CicdConnection(_target(GITLAB), client=fake)
    with pytest.raises(CicdApiError) as ei:
        conn.get("/api/v4/projects/999")
    assert ei.value.status_code == 404
    assert ei.value.path == "/api/v4/projects/999"
    assert "Resource not found" in str(ei.value)


@pytest.mark.unit
def test_transport_error_translated_to_cicd_api_error():
    fake = _FakeClient(exc=httpx.ConnectError("refused"))
    conn = CicdConnection(_target(GITLAB), client=fake)
    with pytest.raises(CicdApiError, match="Could not reach"):
        conn.get("/api/v4/version")


@pytest.mark.unit
def test_close_delegates_to_client_and_properties():
    fake = _FakeClient()
    conn = CicdConnection(_target(GITEA), client=fake)
    assert conn.target.name == "t1"
    assert conn.platform.name == GITEA
    conn.close()
    assert fake.closed is True


# ── ConnectionManager: caching / lifecycle ───────────────────────────────────


class _StubConn:
    def __init__(self, target, client=None):
        self.target = target
        self.closed = False

    def close(self):
        self.closed = True


@pytest.mark.unit
def test_manager_caches_and_reuses_connection_per_target(monkeypatch):
    monkeypatch.setattr("cicd_aiops.connection.CicdConnection", _StubConn)
    cfg = _make_cfg()
    mgr = ConnectionManager(cfg)
    first = mgr.connect("gl")
    second = mgr.connect("gl")
    assert first is second  # session reuse
    assert mgr.list_connected() == ["gl"]


@pytest.mark.unit
def test_manager_default_target_is_first(monkeypatch):
    monkeypatch.setattr("cicd_aiops.connection.CicdConnection", _StubConn)
    mgr = ConnectionManager(_make_cfg())
    conn = mgr.connect()  # no name → default (first) target
    assert conn.target.name == "gl"


@pytest.mark.unit
def test_manager_disconnect_closes_and_forgets(monkeypatch):
    monkeypatch.setattr("cicd_aiops.connection.CicdConnection", _StubConn)
    mgr = ConnectionManager(_make_cfg())
    conn = mgr.connect("gl")
    mgr.disconnect("gl")
    assert conn.closed is True
    assert mgr.list_connected() == []
    mgr.disconnect("gl")  # idempotent: no-op on an absent target


@pytest.mark.unit
def test_manager_disconnect_all_and_list_targets(monkeypatch):
    monkeypatch.setattr("cicd_aiops.connection.CicdConnection", _StubConn)
    mgr = ConnectionManager(_make_cfg())
    mgr.connect("gl")
    mgr.connect("gt")
    assert sorted(mgr.list_targets()) == ["gl", "gt"]
    mgr.disconnect_all()
    assert mgr.list_connected() == []


@pytest.mark.unit
def test_manager_from_config_uses_loader(monkeypatch):
    cfg = _make_cfg()
    monkeypatch.setattr("cicd_aiops.connection.load_config", lambda: cfg)
    mgr = ConnectionManager.from_config()
    assert sorted(mgr.list_targets()) == ["gl", "gt"]


def _make_cfg():
    from cicd_aiops.config import AppConfig

    return AppConfig(
        targets=(
            TargetConfig(name="gl", platform=GITLAB, base_url="https://gl"),
            TargetConfig(name="gt", platform=GITEA, base_url="https://gt"),
        )
    )

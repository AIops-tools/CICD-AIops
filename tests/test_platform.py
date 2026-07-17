"""Platform registry + connection wiring (GitLab + Gitea), config dispatch.

No real server is needed — the httpx client is injected. Proves the registry
maps each platform name to its API shape, path templates format, list payloads
unwrap across both response conventions, and the connection sends the right
auth header (PRIVATE-TOKEN for GitLab, Authorization: token for Gitea) and
translates errors.
"""

import pytest

from cicd_aiops.config import TargetConfig
from cicd_aiops.connection import CicdApiError, CicdConnection
from cicd_aiops.platform import (
    GITEA,
    GITLAB,
    get_platform,
    platform_names,
)


@pytest.mark.unit
def test_both_platforms_registered():
    assert set(platform_names()) == {GITEA, GITLAB}
    assert get_platform(GITLAB).uses_private_token
    assert not get_platform(GITEA).uses_private_token


@pytest.mark.unit
def test_unknown_platform_raises_with_registered_names():
    with pytest.raises(ValueError, match="gitlab"):
        get_platform("jenkins-x")


@pytest.mark.unit
def test_path_templates_differ_per_platform():
    gl = get_platform(GITLAB)
    gt = get_platform(GITEA)
    assert gl.path("version") == "/api/v4/version"
    assert gt.path("version") == "/api/v1/version"
    assert gl.path("pipelines", project=42) == "/api/v4/projects/42/pipelines"
    assert gt.path("pipelines", project="dev/api") == "/api/v1/repos/dev/api/actions/runs"


@pytest.mark.unit
def test_gitlab_project_path_is_single_segment_encoded():
    """GitLab addresses a project by URL-encoded full path — the '/' must
    become %2F (one segment), exactly what the v4 API expects."""
    path = get_platform(GITLAB).path("project", project="group/app")
    assert path == "/api/v4/projects/group%2Fapp"


@pytest.mark.unit
def test_unmapped_resource_raises_teaching_keyerror():
    # Runner administration is not part of Gitea's API v1 → teaching error.
    with pytest.raises(KeyError, match="not available on platform 'gitea'"):
        get_platform(GITEA).path("runners")
    with pytest.raises(KeyError, match="Available resources"):
        get_platform(GITEA).path("pipeline_retry", project="o/r", pipeline=1)


@pytest.mark.unit
def test_rows_unwraps_both_conventions_and_bare_array():
    gl = get_platform(GITLAB)
    assert gl.rows([{"a": 1}, {"a": 2}]) == [{"a": 1}, {"a": 2}]  # bare array
    assert gl.rows({"data": [{"b": 3}]}) == [{"b": 3}]  # Gitea repo search
    assert gl.rows({"workflow_runs": [{"c": 4}]}) == [{"c": 4}]  # Gitea runs
    assert gl.rows({"nope": 1}) == []


@pytest.mark.unit
def test_rows_sanitizes_strings():
    out = get_platform(GITEA).rows({"data": [{"x": "ok", "n": 5}]})
    assert out[0]["x"] == "ok" and out[0]["n"] == 5


class _Resp:
    def __init__(self, status, payload=None, content=b"{}", text="body"):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.content = content
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


@pytest.mark.unit
def test_gitlab_uses_private_token_header(monkeypatch):
    monkeypatch.setenv("CICD_GL1_SECRET", "glpat-xyz")
    target = TargetConfig(name="gl1", platform=GITLAB,
                          base_url="https://git.local", verify_ssl=False)
    headers = CicdConnection._build_headers(target)
    assert headers["PRIVATE-TOKEN"] == "glpat-xyz"
    assert "Authorization" not in headers


@pytest.mark.unit
def test_gitea_uses_token_authorization_header(monkeypatch):
    monkeypatch.setenv("CICD_GT1_SECRET", "gitea-token-abc")
    target = TargetConfig(name="gt1", platform=GITEA,
                          base_url="https://gitea.local", verify_ssl=False)
    headers = CicdConnection._build_headers(target)
    assert headers["Authorization"] == "token gitea-token-abc"
    assert "PRIVATE-TOKEN" not in headers


@pytest.mark.unit
def test_connection_translates_non_2xx(monkeypatch):
    monkeypatch.setenv("CICD_GL1_SECRET", "s")
    target = TargetConfig(name="gl1", platform=GITLAB, base_url="https://h")

    class _Client:
        def request(self, method, path, **k):
            return _Resp(404, content=b"x")

        def close(self):
            pass

    conn = CicdConnection(target, client=_Client())
    with pytest.raises(CicdApiError) as ei:
        conn.get("/api/v4/x")
    assert ei.value.status_code == 404
    assert "not found" in str(ei.value).lower()


@pytest.mark.unit
def test_connection_passes_plain_text_traces_through(monkeypatch):
    """Job trace endpoints return text/plain — the connection must hand the
    text back rather than swallowing it as an empty dict."""
    import json

    monkeypatch.setenv("CICD_GL1_SECRET", "s")
    target = TargetConfig(name="gl1", platform=GITLAB, base_url="https://h")

    class _Client:
        def request(self, method, path, **k):
            return _Resp(
                200,
                payload=json.JSONDecodeError("x", "y", 0),
                content=b"line1\nline2",
                text="line1\nline2",
            )

        def close(self):
            pass

    conn = CicdConnection(target, client=_Client())
    assert conn.get("/api/v4/projects/1/jobs/2/trace") == "line1\nline2"


@pytest.mark.unit
def test_config_rejects_bad_platform_and_normalises_base_url():
    with pytest.raises(ValueError):
        TargetConfig(name="x", platform="jenkins-x", base_url="https://h")
    t = TargetConfig(name="g", platform=GITLAB, base_url="git.example.com/")
    assert t.base_url == "https://git.example.com"  # scheme added, slash trimmed
    assert t.verify_ssl is True  # TLS verification defaults ON


# ── URL-encoding of agent-supplied path segments ─────────────────────────────


@pytest.mark.unit
def test_path_traversal_ids_are_url_encoded():
    """An id carrying ``../`` must not reach the HTTP client as a raw path
    traversal — every substituted value is URL-encoded in Platform.path()."""
    gl = get_platform(GITLAB)
    path = gl.path("pipeline", project="1", pipeline="../../admin/users")
    assert "../" not in path
    assert path.startswith("/api/v4/projects/1/pipelines/")

    path = gl.path("project", project="x&admin=1?y=z")
    assert "&admin" not in path and "?" not in path


@pytest.mark.unit
def test_gitea_multi_segment_project_rejects_traversal():
    """Gitea's owner/repo keeps its '/' — but '..', '.' and empty segments are
    rejected outright, and each piece is individually encoded."""
    gt = get_platform(GITEA)
    assert gt.path("project", project="dev/api") == "/api/v1/repos/dev/api"
    encoded = gt.path("project", project="dev/a b?x=1")
    assert " " not in encoded and "?" not in encoded
    for hostile in ("../etc", "a/../b", "a//b", "/a", "."):
        with pytest.raises(ValueError, match="not allowed"):
            gt.path("project", project=hostile)

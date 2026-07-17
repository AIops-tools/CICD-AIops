"""Connection management for self-managed CI/CD servers (GitLab + Gitea).

Thin httpx wrapper with per-target session reuse. Authentication is selected by
the target's :class:`~cicd_aiops.platform.Platform` descriptor:

  * **GitLab** — the access token is presented in a ``PRIVATE-TOKEN`` header;
    resource paths live under ``/api/v4/...``.
  * **Gitea** — the access token is presented as ``Authorization: token <t>``;
    resource paths live under ``/api/v1/...``.

Ops modules never hard-code a path or a payload key: they ask
``conn.platform.path("pipelines", project=...)`` for the concrete URL and
``conn.platform.rows()`` to unwrap a list payload, so the same op works on both
servers.

All non-2xx responses are translated centrally into ``CicdApiError`` with a
teaching message — HTTP errors are translated at the connection layer rather
than leaking raw tracebacks. The httpx client is injectable for tests: pass
``client=`` a mock implementing ``request`` / ``close``.
"""

from __future__ import annotations

from typing import Any

import httpx

from cicd_aiops.config import AppConfig, TargetConfig, load_config

_TIMEOUT = 30.0


class CicdApiError(Exception):
    """A CI/CD server REST API call failed; carries a teaching message + status."""

    def __init__(self, message: str, *, status_code: int | None = None, path: str = "") -> None:
        self.status_code = status_code
        self.path = path
        super().__init__(message)


def _teaching_message(status: int, path: str, body: str, label: str) -> str:
    """Map a non-2xx status to an actionable, teaching error message."""
    snippet = body[:200].strip()
    if status in (401, 403):
        return (
            f"Authentication/authorization failed ({status}) on {label} {path}. "
            f"Check the access token (GitLab: a personal/project access token "
            f"with 'api' scope under Preferences → Access Tokens; Gitea: an "
            f"access token under Settings → Applications) and that its account "
            f"can see the project. {snippet}"
        )
    if status == 404:
        return (
            f"Resource not found (404) on {label} {path}. The project/pipeline/"
            f"runner id may be stale — list the parent collection first to get "
            f"a current one. {snippet}"
        )
    if status == 400:
        return (
            f"Bad request (400) on {label} {path}. The server rejected the "
            f"request — check required fields and value formats. {snippet}"
        )
    if status == 429:
        return (
            f"Rate limited (429) on {label} {path}. Back off and retry; consider "
            f"raising the instance's rate limits for this token. {snippet}"
        )
    if status in (500, 502, 503, 504):
        return (
            f"{label} server error ({status}) on {path}. The server may be "
            f"busy; retry shortly. {snippet}"
        )
    return f"{label} API error ({status}) on {path}. {snippet}"


class CicdConnection:
    """A single authenticated session against one GitLab or Gitea target."""

    def __init__(self, target: TargetConfig, client: Any | None = None) -> None:
        self._target = target
        self._client = client or httpx.Client(
            base_url=target.base_url,
            verify=target.verify_ssl,
            timeout=_TIMEOUT,
            headers=self._build_headers(target),
        )

    @staticmethod
    def _build_headers(target: TargetConfig) -> dict[str, str]:
        """GitLab wants ``PRIVATE-TOKEN``; Gitea ``Authorization: token <t>``."""
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if target.platform_obj.uses_private_token:
            headers["PRIVATE-TOKEN"] = target.secret
        else:
            headers["Authorization"] = f"token {target.secret}"
        return headers

    @property
    def target(self) -> TargetConfig:
        return self._target

    @property
    def platform(self) -> Any:
        return self._target.platform_obj

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        label = self._target.platform_obj.label
        try:
            resp = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise CicdApiError(
                f"Could not reach {label} at {self._target.base_url} "
                f"({method} {path}): {exc}. Check base_url and reachability.",
                path=path,
            ) from exc
        if not (200 <= resp.status_code < 300):
            raise CicdApiError(
                _teaching_message(resp.status_code, path, resp.text, label),
                status_code=resp.status_code,
                path=path,
            )
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            # Some endpoints (job traces/logs) return plain text — pass through.
            return resp.text

    def get(self, path: str, **kwargs: Any) -> Any:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self._request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self._request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Any:
        return self._request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self._request("DELETE", path, **kwargs)

    def close(self) -> None:
        self._client.close()


class ConnectionManager:
    """Manages connections to multiple CI/CD targets with session reuse."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._connections: dict[str, CicdConnection] = {}

    @classmethod
    def from_config(cls, config: AppConfig | None = None) -> ConnectionManager:
        cfg = config or load_config()
        return cls(cfg)

    def connect(self, target_name: str | None = None) -> CicdConnection:
        target = (
            self._config.get_target(target_name)
            if target_name
            else self._config.default_target
        )
        cached = self._connections.get(target.name)
        if cached is not None:
            return cached
        conn = CicdConnection(target)
        self._connections[target.name] = conn
        return conn

    def disconnect(self, target_name: str) -> None:
        conn = self._connections.pop(target_name, None)
        if conn is not None:
            conn.close()

    def disconnect_all(self) -> None:
        for name in list(self._connections):
            self.disconnect(name)

    def list_targets(self) -> list[str]:
        return [t.name for t in self._config.targets]

    def list_connected(self) -> list[str]:
        return list(self._connections.keys())

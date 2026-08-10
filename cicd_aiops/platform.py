"""Platform descriptors — the self-managed CI/CD servers cicd-aiops speaks to.

cicd-aiops is multi-platform by construction. A registry maps a *platform
name* to a :class:`Platform` descriptor that captures everything the connection
and ops layers need to talk to that server: how it authenticates, the concrete
REST path for each *logical resource*, and how a raw response is normalised
(injection-safe). Because GitLab and Gitea expose the same CI/CD concepts
behind different URLs and auth headers, the ops modules ask the platform
for a path (``conn.platform.path("pipelines", project=...)``) and for the row
list of a payload (``conn.platform.rows(payload)``) instead of hard-coding
either — so the same tool works on both.

v0.1 registers two platforms (SELF-MANAGED instances only):

  * **gitlab** — GitLab REST API v4 (``/api/v4/...``) with a personal/project
    access token presented in a ``PRIVATE-TOKEN`` header.
  * **gitea** — Gitea API v1 (``/api/v1/...``) with an access token presented
    as ``Authorization: token <token>``.

Where Gitea lacks an equivalent surface (e.g. runner administration, bulk
artifact deletion, pipeline retry/cancel), the resource is simply *not mapped*
— asking for it raises the standard teaching ``KeyError`` listing what *is*
available on that platform.

Additional forges can ``register`` their own descriptor later without touching
the ops / CLI / MCP layers — a registry keyed by ``platform`` name. The
concrete REST paths below are modelled from each project's public API docs and
are exercised against mocked HTTP responses only; see the README's preview note.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from cicd_aiops.governance import sanitize


def _seg(value: Any) -> str:
    """URL-encode one path/query value so agent-supplied identifiers (project
    paths, pipeline ids, branch names) cannot smuggle ``/``, ``../`` or query
    metacharacters into the request URL."""
    return quote(str(value), safe="")


def _multi_seg(value: Any) -> str:
    """Encode an ``owner/repo``-style value as *separate* URL path segments.

    Gitea addresses repositories as two literal path segments, so the ``/``
    must survive — but every piece is still individually encoded and a piece
    that is empty, ``.`` or ``..`` is rejected outright (path traversal).
    """
    pieces = str(value).split("/")
    for piece in pieces:
        if piece in ("", ".", ".."):
            raise ValueError(
                f"Invalid path segment {piece!r} in {str(value)!r}: "
                f"empty, '.' and '..' segments are not allowed."
            )
    return "/".join(_seg(p) for p in pieces)


# ─── registered platform names ──────────────────────────────────────────────
GITLAB = "gitlab"
GITEA = "gitea"
PLATFORMS = (GITLAB, GITEA)

# Auth styles.
AUTH_PRIVATE_TOKEN = "private-token"  # nosec B105 — PRIVATE-TOKEN: <token> (GitLab)
AUTH_TOKEN_PREFIX = "token-prefix"  # nosec B105 — Authorization: token <token> (Gitea)

# Bounds for the response normaliser (defensive against a hostile server).
_MAX_STR = 512
_MAX_DEPTH = 8

# Keys under which each platform wraps a list payload, tried in order before
# falling back to a bare JSON array. GitLab returns bare arrays; Gitea wraps
# some collections (repo search → ``data``, action runs → ``workflow_runs``).
_LIST_KEYS = ("workflow_runs", "jobs", "artifacts", "data", "rows", "results", "items")


def _sanitize_obj(obj: Any, depth: int = 0) -> Any:
    """Recursively fold server-returned JSON into injection-safe values.

    Every string leaf passes through ``sanitize`` (bounded length); numbers,
    booleans and ``None`` pass through unchanged. Depth is capped so a
    pathological nesting cannot exhaust the stack.
    """
    if depth > _MAX_DEPTH:
        return None
    if isinstance(obj, dict):
        return {str(k): _sanitize_obj(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_obj(v, depth + 1) for v in obj]
    if isinstance(obj, str):
        return sanitize(obj, _MAX_STR)
    return obj


class UnsupportedResource(KeyError):  # noqa: N818 — teaching error, reads as a statement
    """A resource this platform genuinely does not expose.

    Subclasses ``KeyError`` so existing ``except KeyError`` handlers keep
    working, but is distinguishable — a bare ``KeyError`` here was being
    reported by the CLI as "Missing required key or environment variable",
    sending the operator to hunt a config problem that does not exist. The
    real cause (this platform has no such resource) was buried in the detail.
    """


@dataclass(frozen=True)
class Platform:
    """A CI/CD server's API shape: auth style + logical-resource path map."""

    name: str
    label: str
    auth_style: str
    paths: dict[str, str] = field(default_factory=dict)
    # Keys whose values may contain '/' as a segment separator (Gitea's
    # owner/repo). Every other substitution is single-segment encoded.
    multi_seg_keys: frozenset[str] = frozenset()

    @property
    def uses_private_token(self) -> bool:
        return self.auth_style == AUTH_PRIVATE_TOKEN

    def path(self, resource: str, **fmt: Any) -> str:
        """Return the concrete REST path for a logical ``resource``.

        Raises a teaching ``KeyError`` when the resource is not mapped for this
        platform (so a caller asking for an unsupported surface fails fast with
        the list of what *is* available, rather than hitting a confusing 404).

        Every substituted value is URL-encoded (``quote(..., safe="")``) so an
        agent-supplied identifier can never rewrite the path (e.g. via ``../``).
        Keys in ``multi_seg_keys`` keep ``/`` as a separator but each piece is
        encoded and ``.``/``..``/empty pieces are rejected.
        """
        try:
            template = self.paths[resource]
        except KeyError as exc:
            available = ", ".join(sorted(self.paths)) or "(none)"
            raise UnsupportedResource(
                f"Resource '{resource}' is not available on platform '{self.name}'. "
                f"Available resources: {available}."
            ) from exc
        if not fmt:
            return template
        encoded = {
            k: (_multi_seg(v) if k in self.multi_seg_keys else _seg(v))
            for k, v in fmt.items()
        }
        return template.format(**encoded)

    def supports(self, resource: str) -> bool:
        return resource in self.paths

    def rows(self, payload: Any) -> list[dict]:
        """Normalise a list payload to a sanitised list of dict rows.

        A bare JSON array passes through (GitLab's convention); a dict is
        unwrapped via the first wrapper key that is present (Gitea wraps repo
        search under ``data`` and action runs under ``workflow_runs``). Every
        row is run through the injection-safe normaliser.
        """
        if isinstance(payload, dict):
            items: Any = []
            for key in _LIST_KEYS:
                value = payload.get(key)
                if isinstance(value, list):
                    items = value
                    break
        else:
            items = payload
        return [_sanitize_obj(r) for r in (items or []) if isinstance(r, dict)]

    def normalise(self, payload: Any) -> Any:
        """Return an injection-safe copy of a raw response payload."""
        return _sanitize_obj(payload)


# ─── registry ───────────────────────────────────────────────────────────────
_REGISTRY: dict[str, Platform] = {}


def register(platform: Platform) -> None:
    """Register a platform descriptor under its name (idempotent overwrite)."""
    _REGISTRY[platform.name] = platform


def get_platform(name: str) -> Platform:
    """Return the descriptor for ``name`` or raise with the registered names."""
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise ValueError(
            f"Unknown platform '{name}'. Registered platforms: {available}."
        ) from exc


def platform_names() -> tuple[str, ...]:
    """All registered platform names (sorted)."""
    return tuple(sorted(_REGISTRY))


# ─── GitLab (REST v4 /api/v4/..., PRIVATE-TOKEN header) ──────────────────────
# {project} is the numeric id or the full path — encoded as a SINGLE segment
# (GitLab itself expects 'group%2Fproject').
_GITLAB_PATHS = {
    # server
    "version": "/api/v4/version",
    "current_user": "/api/v4/user",
    # projects
    "projects": "/api/v4/projects",
    "project": "/api/v4/projects/{project}",
    # pipelines + jobs
    "pipelines": "/api/v4/projects/{project}/pipelines",
    "pipeline": "/api/v4/projects/{project}/pipelines/{pipeline}",
    "pipeline_jobs": "/api/v4/projects/{project}/pipelines/{pipeline}/jobs",
    "pipeline_retry": "/api/v4/projects/{project}/pipelines/{pipeline}/retry",
    "pipeline_cancel": "/api/v4/projects/{project}/pipelines/{pipeline}/cancel",
    "jobs": "/api/v4/projects/{project}/jobs",
    "job_trace": "/api/v4/projects/{project}/jobs/{job}/trace",
    # runners
    "runners": "/api/v4/runners/all",
    "runner": "/api/v4/runners/{runner}",
    "runner_update": "/api/v4/runners/{runner}",
    # repo surface
    "merge_requests": "/api/v4/projects/{project}/merge_requests",
    "branches": "/api/v4/projects/{project}/repository/branches",
    "protected_branches": "/api/v4/projects/{project}/protected_branches",
    "protected_branch": "/api/v4/projects/{project}/protected_branches/{branch}",
    "releases": "/api/v4/projects/{project}/releases",
    # artifacts
    "artifacts_delete": "/api/v4/projects/{project}/artifacts",
    "job_artifacts_delete": "/api/v4/projects/{project}/jobs/{job}/artifacts",
    # settings
    "project_settings": "/api/v4/projects/{project}",
}

# ─── Gitea (API v1 /api/v1/..., Authorization: token <token>) ─────────────────
# {project} is 'owner/repo' — two literal path segments (multi_seg encoding).
# Runner administration, pipeline retry/cancel and bulk artifact deletion have
# no public API v1 equivalent → intentionally unmapped (teaching error).
_GITEA_PATHS = {
    # server
    "version": "/api/v1/version",
    "current_user": "/api/v1/user",
    # projects (repositories)
    "projects": "/api/v1/repos/search",
    "project": "/api/v1/repos/{project}",
    # Jobs — but NOT pipeline runs. Gitea API v1 has no run-level resource:
    # `/actions/runs`, `/actions/runs/{id}` and `/actions/runs/{id}/jobs` do not
    # exist (confirmed against the server's own swagger.v1.json on 1.24.7, where
    # the only `/actions/runs/...` path is `/{run}/artifacts`). They were mapped
    # anyway, so every pipeline call 404'd on a real Gitea. `/actions/tasks` is
    # the per-JOB listing — its rows are individual jobs that share a
    # `run_number`, despite the payload calling them `workflow_runs`. Leaving
    # the run-level keys unmapped makes them raise UnsupportedResource, which
    # names the limit instead of returning a 404 nobody can act on.
    "jobs": "/api/v1/repos/{project}/actions/tasks",
    "job_trace": "/api/v1/repos/{project}/actions/jobs/{job}/logs",
    # repo surface
    "merge_requests": "/api/v1/repos/{project}/pulls",
    "branches": "/api/v1/repos/{project}/branches",
    "protected_branches": "/api/v1/repos/{project}/branch_protections",
    "protected_branch": "/api/v1/repos/{project}/branch_protections/{branch}",
    "releases": "/api/v1/repos/{project}/releases",
    # artifacts (Gitea Actions artifacts — list only; no bulk delete API)
    "artifacts": "/api/v1/repos/{project}/actions/artifacts",
}


register(
    Platform(
        name=GITLAB,
        label="GitLab REST API v4 (self-managed)",
        auth_style=AUTH_PRIVATE_TOKEN,
        paths=_GITLAB_PATHS,
    )
)
register(
    Platform(
        name=GITEA,
        label="Gitea API v1 (self-hosted)",
        auth_style=AUTH_TOKEN_PREFIX,
        paths=_GITEA_PATHS,
        multi_seg_keys=frozenset({"project"}),
    )
)


__all__ = [
    "GITLAB",
    "GITEA",
    "PLATFORMS",
    "AUTH_PRIVATE_TOKEN",
    "AUTH_TOKEN_PREFIX",
    "Platform",
    "register",
    "get_platform",
    "platform_names",
]

"""Configuration management for CICD AIops.

Loads CI/CD server connection targets from a YAML config file. Each target
names its ``platform`` — ``gitlab`` (GitLab REST API v4, self-managed) or
``gitea`` (Gitea API v1, self-hosted) — so one config can span a mixed estate.
See :mod:`cicd_aiops.platform` for how the platform name selects the API shape
(auth header + resource paths).

Targets carry a full ``base_url`` (e.g. ``https://gitlab.example.com``) because
self-managed servers commonly live behind reverse proxies on non-default ports.
TLS verification defaults to ON.

The access token is NEVER stored in the config file or in plaintext on disk:
it lives in the encrypted store ``~/.cicd-aiops/secrets.enc`` (see
:mod:`cicd_aiops.secretstore`). For GitLab it is a personal/project access
token (``PRIVATE-TOKEN`` header); for Gitea an access token
(``Authorization: token ...``). A legacy env var (``CICD_<TARGET>_SECRET``) is
honoured as a fallback.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from cicd_aiops.governance.paths import ops_home
from cicd_aiops.platform import GITLAB, PLATFORMS, get_platform
from cicd_aiops.secretstore import (
    MasterPasswordError,
    SecretStoreError,
    get_secret,
    has_store,
)

if TYPE_CHECKING:
    from cicd_aiops.platform import Platform

CONFIG_DIR = ops_home()
CONFIG_FILE = CONFIG_DIR / "config.yaml"
ENV_FILE = CONFIG_DIR / ".env"

SECRET_ENV_PREFIX = "CICD_"  # nosec B105 — env-var name, not a secret
SECRET_ENV_SUFFIX = "_SECRET"  # nosec B105 — env-var name, not a secret

_log = logging.getLogger("cicd-aiops.config")


def _secret_env_key(name: str) -> str:
    """Legacy per-target token env var name, e.g. CICD_GL1_SECRET."""
    return f"{SECRET_ENV_PREFIX}{name.upper().replace('-', '_')}{SECRET_ENV_SUFFIX}"


def _resolve_secret(name: str) -> str:
    """Return a target's token: encrypted store first, then legacy env var."""
    if has_store():
        try:
            return get_secret(name)
        except MasterPasswordError:
            # A wrong or missing master password is NOT "this target has no
            # secret". Falling through resurfaced it as "No API key for target
            # X", sending the operator to add a credential that is already
            # there. MasterPasswordError subclasses SecretStoreError, so the
            # broad catch below would swallow it — re-raise first.
            raise
        except SecretStoreError:
            pass  # no secret stored for this target — try the legacy env var
    legacy = os.environ.get(_secret_env_key(name))
    if legacy:
        _log.warning(
            "Using plaintext env var %s. Migrate to the encrypted store with "
            "'cicd-aiops secret migrate'.",
            _secret_env_key(name),
        )
        return legacy
    raise OSError(
        f"No token for target '{name}'. Add one with "
        f"'cicd-aiops secret set {name}' (stored encrypted), or run "
        f"'cicd-aiops init'."
    )


@dataclass(frozen=True)
class TargetConfig:
    """A connection target for one self-managed CI/CD server.

    ``platform`` is ``gitlab`` or ``gitea`` (validated at construction).
    ``base_url`` is the server root (scheme + host [+ port]); the access token
    comes from the encrypted store.
    """

    name: str
    platform: str = GITLAB
    base_url: str = ""
    verify_ssl: bool = True

    def __post_init__(self) -> None:
        if self.platform not in PLATFORMS:
            raise ValueError(
                f"Target '{self.name}': platform must be one of {PLATFORMS}, "
                f"got '{self.platform}'."
            )
        url = self.base_url.strip().rstrip("/")
        if url and not url.startswith(("https://", "http://")):
            url = f"https://{url}"
        object.__setattr__(self, "base_url", url)

    @property
    def platform_obj(self) -> Platform:
        return get_platform(self.platform)

    @property
    def secret(self) -> str:
        return _resolve_secret(self.name)


@dataclass(frozen=True)
class AppConfig:
    """Top-level application config."""

    targets: tuple[TargetConfig, ...] = ()

    def get_target(self, name: str) -> TargetConfig:
        for t in self.targets:
            if t.name == name:
                return t
        available = ", ".join(t.name for t in self.targets) or "(none)"
        raise KeyError(f"Target '{name}' not found. Available: {available}")

    @property
    def default_target(self) -> TargetConfig:
        if not self.targets:
            raise ValueError("No targets configured. Check config.yaml")
        return self.targets[0]


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load config from YAML; the token comes from the encrypted store."""
    path = config_path or CONFIG_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            f"Run 'cicd-aiops init' to set up a GitLab or Gitea target, "
            f"or create {CONFIG_FILE} with a 'targets' list."
        )

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    targets = tuple(
        TargetConfig(
            name=t["name"],
            platform=t.get("platform", GITLAB),
            base_url=t.get("base_url", ""),
            verify_ssl=t.get("verify_ssl", True),
        )
        for t in raw.get("targets", [])
    )

    return AppConfig(targets=targets)

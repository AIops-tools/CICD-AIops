"""Shared helpers for the CI/CD ops modules.

GitLab and Gitea return the same CI/CD concepts under different JSON field
names (e.g. a pipeline's ref is GitLab ``ref`` vs Gitea Actions ``head_branch``).
The ops modules stay platform-neutral by asking the platform for paths/rows
(see :mod:`cicd_aiops.platform`) and by reading fields through :func:`pick`,
which tries a list of candidate keys. All server text reaches the caller only
after ``sanitize()`` via ``s``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from cicd_aiops.governance import sanitize


def as_obj(data: Any) -> dict:
    """Return ``data`` as a dict (empty dict if it isn't one)."""
    return data if isinstance(data, dict) else {}


def s(value: Any, limit: int = 256) -> str:
    """Sanitize an arbitrary value to a bounded, injection-safe string."""
    return sanitize(str(value if value is not None else ""), limit)


def pick(row: dict, *keys: str, default: Any = None) -> Any:
    """Return the first present, non-None value among ``keys`` (else ``default``)."""
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return default


_TRUE = {"1", "true", "yes", "on", "enabled", "active", "online"}
_FALSE = {"0", "false", "no", "off", "disabled", "", "none", "offline"}


def to_bool(value: Any) -> bool:
    """Coerce a server truthy/falsy cell (``"1"``, ``true``, ``"yes"``) to bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return bool(text)


def num(value: Any) -> float:
    """Coerce a numeric cell to float; 0.0 when absent/non-numeric."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def parse_ts(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp (both platforms' convention) to aware UTC.

    Returns ``None`` when absent or unparseable — callers treat unknown ages
    conservatively rather than crashing on a malformed cell.
    """
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def age_days(value: Any, now: datetime | None = None) -> float | None:
    """Age of an ISO timestamp in days (fractional); None when unparseable."""
    dt = parse_ts(value)
    if dt is None:
        return None
    ref = now or datetime.now(UTC)
    return (ref - dt).total_seconds() / 86400.0


def age_seconds(value: Any, now: datetime | None = None) -> float | None:
    """Age of an ISO timestamp in seconds; None when unparseable."""
    dt = parse_ts(value)
    if dt is None:
        return None
    ref = now or datetime.now(UTC)
    return (ref - dt).total_seconds()

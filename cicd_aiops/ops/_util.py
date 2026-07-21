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

from cicd_aiops.governance import opt_str, sanitize


def as_obj(data: Any) -> dict:
    """Return ``data`` as a dict (empty dict if it isn't one)."""
    return data if isinstance(data, dict) else {}


def s(value: Any, limit: int = 256) -> str:
    """Sanitize an arbitrary value to a bounded, injection-safe string."""
    return sanitize(str(value if value is not None else ""), limit)


def opt(value: Any, limit: int = 256) -> str | None:
    """Sanitize a value that may legitimately be absent, preserving absence.

    Companion to :func:`s`, which folds ``None`` into ``""``. Use this for any
    field the server may simply not return (a pipeline with no ``ref``, a job
    that never started, a runner that has never contacted): the caller then
    sees ``null`` — "the server did not report this" — instead of ``""``, which
    reads as "the field exists and is empty". A smaller local model cannot
    recover that difference and tends to invent one.
    """
    return opt_str(value, limit)


def page_limit(limit: Any, page_max: int) -> tuple[int, int]:
    """Return ``(requested, per_page)`` so truncation can always be MEASURED.

    ``per_page`` is always one greater than ``requested``, so a listing can tell
    "there was exactly one more row" from "the list happened to end here" — the
    truncation flag is a measurement, never a guess from
    ``len(rows) == limit``. Because both platforms cap a page at ``page_max``
    rows, ``requested`` is bounded at ``page_max - 1`` to keep room for that
    extra row.
    """
    requested = max(1, min(int(limit), page_max - 1))
    return requested, requested + 1


def listing(key: str, items: list, requested: int, truncated: bool, **extra: Any) -> dict:
    """Build the standard listing envelope around ``items``.

    Every listing returns ``{..., "returned": N, "limit": L, "truncated":
    bool, "<key>": [...]}`` so a cut-off result announces itself instead of
    looking like a complete one. There is deliberately no ``total``: this helper
    only sees the already-sliced page, so a total would just echo ``returned``
    while reading like a server-side count.
    """
    out: dict[str, Any] = dict(extra)
    # No "total": this helper only ever sees the already-sliced page, so any
    # total would merely echo "returned" and read as a server-side count.
    out["returned"] = len(items)
    out["limit"] = requested
    out["truncated"] = truncated
    out[key] = items
    return out


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
    """Coerce a genuinely fractional cell to float; 0.0 when absent/non-numeric.

    For integer quantities — byte counts, counts, whole seconds — use
    :func:`as_int`, which keeps them integers. GitLab's ``repository_size`` /
    ``storage_size`` are integer byte counts; routing them through ``num`` printed
    ``3870.0`` bytes, arithmetically right but semantically wrong.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def as_int(value: Any) -> int:
    """Coerce an integer quantity (bytes/counts/whole seconds) to int; 0 if absent.

    A count or byte total cannot be fractional. Accepts ``"3870"`` and ``3870.0``.
    Keep :func:`num` for genuine ratios/rates.
    """
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


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

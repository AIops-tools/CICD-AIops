"""Shared MCP server primitives: the FastMCP instance, connection helper,
error sanitisation, and the ``@tool_errors`` decorator.

Tool modules under ``mcp_server/tools/`` import ``mcp`` from here and register
their ``@mcp.tool()`` functions onto it. ``mcp_server/server.py`` then imports
those modules and runs the server.

Keep ``Optional[X]`` (never PEP 604 ``X | None``) in any FastMCP-reflected
tool signature — on older mcp/pydantic the union eval'd to ``types.UnionType``
crashes FastMCP's ``issubclass`` check.
"""

import functools
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from cicd_aiops.config import load_config
from cicd_aiops.connection import CicdApiError, ConnectionManager
from cicd_aiops.governance import sanitize

logger = logging.getLogger(__name__)

_DOCTOR_HINT = "Run 'cicd-aiops doctor' to verify connectivity and credentials."


def _safe_error(exc: Exception, tool: str) -> str:
    """Return an agent-safe error string; log full detail server-side only."""
    logger.error("Tool %s failed", tool, exc_info=True)
    _passthrough = (
        ValueError,
        FileNotFoundError,
        KeyError,
        PermissionError,
        TimeoutError,
        ConnectionError,
        CicdApiError,
    )
    if isinstance(exc, _passthrough):
        return sanitize(str(exc), 300)
    return f"{type(exc).__name__}: operation failed."


def tool_errors(shape: str = "dict") -> Callable:
    """Wrap a tool body in the canonical try/except → ``_safe_error`` pattern.

    Place this *between* ``@governed_tool`` and the function so the audit
    decorator and FastMCP still see the original signature.
    """

    def decorator(func: Callable) -> Callable:
        name = func.__name__

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:  # noqa: BLE001 — sanitised below
                msg = _safe_error(e, name)
                if shape == "list":
                    return [{"error": msg, "hint": _DOCTOR_HINT}]
                if shape == "str":
                    return f"Error: {msg} {_DOCTOR_HINT}"
                return {"error": msg, "hint": _DOCTOR_HINT}

        return wrapper

    return decorator


mcp = FastMCP(
    "cicd-aiops",
    instructions=(
        "CI/CD operations over self-managed GitLab and self-hosted "
        "Gitea: server version and token identity; projects with storage "
        "statistics; pipelines, jobs and trace tails; runners; merge/pull "
        "requests, branches, protection rules and releases; artifact "
        "inventories. Flagship analyses: pipeline_failure_rca, "
        "runner_health_rca, artifact_storage_bloat_analysis, stale_work_audit "
        "— transparent heuristics that show their numbers. Governed writes — "
        "retry_pipeline / cancel_pipeline (priorState recorded), pause_runner "
        "/ resume_runner (a reversible undo pair), update_branch_protection "
        "(undo replays the prior settings), plus delete_artifacts at risk=high "
        "with a dry_run preview and an approver. Every tool runs through the "
        "cicd-aiops governance harness (audit / budget / risk-tier / undo). "
        "The same tools work on both servers: a per-target 'platform' field "
        "selects the API shape; surfaces one platform lacks raise a teaching "
        "error. Do NOT use this for Kubernetes deploy state — use k8s-aiops."
    ),
)

_conn_mgr: Optional[ConnectionManager] = None


def _get_connection(target: Optional[str] = None) -> Any:
    """Return a CI/CD server connection, lazily initialising the manager."""
    global _conn_mgr  # noqa: PLW0603
    if _conn_mgr is None:
        config_path_str = os.environ.get("CICD_AIOPS_CONFIG")
        config_path = Path(config_path_str) if config_path_str else None
        _conn_mgr = ConnectionManager(load_config(config_path))
    return _conn_mgr.connect(target)

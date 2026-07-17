"""Artifact reads — per-project artifact inventory with sizes and expiry.

GitLab has no single "list artifacts" endpoint: artifact facts ride on the
jobs list (each job carries an ``artifacts`` array plus
``artifacts_expire_at``), so the GitLab path walks recent jobs. Gitea exposes
Actions artifacts directly under ``/actions/artifacts``. Deletion lives in
:mod:`cicd_aiops.ops.writes`.
"""

from __future__ import annotations

from typing import Any

from cicd_aiops.ops._util import age_days, num, pick, s
from cicd_aiops.platform import GITLAB

_MAX_JOBS = 100


def _gitlab_artifact_rows(conn: Any, project: str) -> list[dict]:
    """Flatten GitLab job rows into one row per artifact file."""
    rows = conn.platform.rows(
        conn.get(
            conn.platform.path("jobs", project=project),
            params={"per_page": _MAX_JOBS},
        )
    )
    out: list[dict] = []
    for job in rows:
        files = job.get("artifacts") or []
        expire_at = pick(job, "artifacts_expire_at", default="")
        for f in files:
            if not isinstance(f, dict):
                continue
            out.append(
                {
                    "jobId": s(pick(job, "id")),
                    "jobName": s(pick(job, "name")),
                    "file": s(pick(f, "filename", "file_type")),
                    "sizeBytes": num(pick(f, "size", default=0)),
                    "createdAt": s(pick(job, "finished_at", "created_at", default="")),
                    "expireAt": s(expire_at or ""),
                }
            )
    return out


def _gitea_artifact_rows(conn: Any, project: str) -> list[dict]:
    rows = conn.platform.rows(conn.get(conn.platform.path("artifacts", project=project)))
    return [
        {
            "jobId": s(pick(r, "workflow_run_id", "run_id", default="")),
            "jobName": s(pick(r, "workflow_name", default="")),
            "file": s(pick(r, "name")),
            "sizeBytes": num(pick(r, "size_in_bytes", "size", default=0)),
            "createdAt": s(pick(r, "created_at", default="")),
            "expireAt": s(pick(r, "expires_at", default="")),
        }
        for r in rows
    ]


def list_artifacts(conn: Any, project: str) -> dict:
    """[READ] Artifact inventory for a project: files, sizes, expiry."""
    try:
        if conn.target.platform == GITLAB:
            artifacts = _gitlab_artifact_rows(conn, project)
        else:
            artifacts = _gitea_artifact_rows(conn, project)
        total_bytes = sum(a["sizeBytes"] for a in artifacts)
        expired_kept = [
            a for a in artifacts if a["expireAt"] and (age_days(a["expireAt"]) or 0) > 0
        ]
        return {
            "project": s(project),
            "total": len(artifacts),
            "totalBytes": total_bytes,
            "expiredButKept": len(expired_kept),
            "artifacts": artifacts,
        }
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "project": s(project)}


def pull_artifacts(conn: Any, project: str) -> list[dict]:
    """[READ] Live artifact rows for one project (feeds the bloat RCA)."""
    out = list_artifacts(conn, project)
    return out.get("artifacts", []) if isinstance(out, dict) and "error" not in out else []

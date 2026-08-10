"""Artifact reads — per-project artifact inventory with sizes and expiry.

GitLab has no single "list artifacts" endpoint: artifact facts ride on the
jobs list (each job carries an ``artifacts`` array plus
``artifacts_expire_at``), so the GitLab path walks recent jobs. Gitea exposes
Actions artifacts directly under ``/actions/artifacts``. Deletion lives in
:mod:`cicd_aiops.ops.writes`.

Because the GitLab inventory is assembled from a *bounded* job scan, the result
reports how many jobs were scanned and whether that scan itself was cut short
(``jobScanTruncated``) — an artifact inventory that quietly missed half the
jobs would otherwise read as a complete one.
"""

from __future__ import annotations

from typing import Any

from cicd_aiops.ops._util import age_days, as_int, listing, opt, page_limit, pick, s
from cicd_aiops.platform import GITLAB

_MAX_JOBS = 100
_MAX_ARTIFACTS = 500


def _gitlab_artifact_rows(conn: Any, project: str) -> tuple[list[dict], bool, int]:
    """Flatten GitLab job rows into one row per artifact file.

    Returns ``(rows, job_scan_truncated, jobs_scanned)``. One job beyond the
    scan bound is requested so the truncation flag is measured.
    """
    scanned, per_page = page_limit(_MAX_JOBS, _MAX_JOBS)
    job_rows = conn.platform.rows(
        conn.get(
            conn.platform.path("jobs", project=project),
            params={"per_page": per_page},
        )
    )
    scan_truncated = len(job_rows) > scanned
    out: list[dict] = []
    for job in job_rows[:scanned]:
        files = job.get("artifacts") or []
        expire_at = pick(job, "artifacts_expire_at")
        for f in files:
            if not isinstance(f, dict):
                continue
            out.append(
                {
                    "jobId": s(pick(job, "id")),
                    "jobName": opt(pick(job, "name")),
                    "file": s(pick(f, "filename", "file_type")),
                    # The job log is listed as an artifact but is NOT removed by
                    # the job-artifacts delete, so callers must be able to tell
                    # it apart before counting what a deletion destroys.
                    "fileType": opt(pick(f, "file_type")),
                    "sizeBytes": as_int(pick(f, "size", default=0)),
                    "createdAt": opt(pick(job, "finished_at", "created_at")),
                    "expireAt": opt(expire_at),
                }
            )
    return out, scan_truncated, min(len(job_rows), scanned)


def _gitea_artifact_rows(conn: Any, project: str) -> list[dict]:
    rows = conn.platform.rows(conn.get(conn.platform.path("artifacts", project=project)))
    return [
        {
            "jobId": opt(pick(r, "workflow_run_id", "run_id")),
            "jobName": opt(pick(r, "workflow_name")),
            "file": s(pick(r, "name")),
            "fileType": opt(pick(r, "file_type")),
            "sizeBytes": as_int(pick(r, "size_in_bytes", "size", default=0)),
            "createdAt": opt(pick(r, "created_at")),
            "expireAt": opt(pick(r, "expires_at")),
        }
        for r in rows
    ]


def list_artifacts(conn: Any, project: str, limit: int = _MAX_ARTIFACTS) -> dict:
    """[READ] Artifact inventory for a project: files, sizes, expiry.

    ``totalBytes`` / ``expiredButKept`` are computed over **every** artifact
    found, not just the rows returned, so the numbers stay correct when the row
    list is cut; ``truncated`` then says the rows are a subset. On GitLab the
    inventory is assembled from a bounded job scan — ``jobScanTruncated`` says
    whether that scan reached the end of the job list.
    """
    try:
        job_scan_truncated = False
        jobs_scanned = None
        if conn.target.platform == GITLAB:
            artifacts, job_scan_truncated, jobs_scanned = _gitlab_artifact_rows(
                conn, project
            )
        else:
            artifacts = _gitea_artifact_rows(conn, project)
        total_bytes = sum(a["sizeBytes"] for a in artifacts)
        expired_kept = [
            a for a in artifacts if a["expireAt"] and (age_days(a["expireAt"]) or 0) > 0
        ]
        requested = max(1, int(limit))
        truncated = len(artifacts) > requested
        return listing(
            "artifacts",
            artifacts[:requested],
            requested,
            truncated,
            project=s(project),
            totalBytes=total_bytes,
            expiredButKept=len(expired_kept),
            artifactsFound=len(artifacts),
            jobsScanned=jobs_scanned,
            jobScanTruncated=job_scan_truncated,
        )
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": s(exc, 200), "project": s(project)}


def pull_artifacts(conn: Any, project: str) -> list[dict]:
    """[READ] Live artifact rows for one project (feeds the bloat RCA)."""
    out = list_artifacts(conn, project)
    return out.get("artifacts", []) if isinstance(out, dict) and "error" not in out else []

"""Unit tests for the four flagship analyses (pure functions, no I/O)."""

from datetime import UTC, datetime

import pytest

from cicd_aiops.ops import analysis as ops

NOW = datetime(2026, 7, 17, 12, 0, 0, tzinfo=UTC)


# ── 1. pipeline-failure RCA ──────────────────────────────────────────────────


def _failed_pipeline(pid, jobs):
    return {"id": pid, "ref": "main", "status": "failed", "jobs": jobs}


@pytest.mark.unit
def test_pipeline_failure_rca_classifies_from_trace_markers():
    pipelines = [
        _failed_pipeline("1", [
            {"name": "unit", "stage": "test", "status": "failed",
             "failureReason": "script_failure",
             "traceTail": "E AssertionError: expected 3 == 4\n2 failed"},
        ]),
        _failed_pipeline("2", [
            {"name": "build", "stage": "build", "status": "failed",
             "failureReason": "script_failure",
             "traceTail": "curl: (6) Could not resolve host: registry.local"},
        ]),
        _failed_pipeline("3", [
            {"name": "compile", "stage": "build", "status": "failed",
             "failureReason": "script_failure",
             "traceTail": "g++: fatal error: Killed ... cannot allocate memory"},
        ]),
        _failed_pipeline("4", [
            {"name": "e2e", "stage": "verify", "status": "failed",
             "failureReason": "stuck_or_timeout_failure", "traceTail": ""},
        ]),
        _failed_pipeline("5", [
            {"name": "deploy-docs", "stage": "publish", "status": "failed",
             "failureReason": "script_failure",
             "traceTail": "/bin/sh: mkdocs: command not found"},
        ]),
    ]
    out = ops.pipeline_failure_rca(pipelines)
    assert out["pipelinesEvaluated"] == 5
    classes = {p["pipeline"]: p["headlineClass"] for p in out["pipelines"]}
    assert classes == {
        "1": "test-failure",
        "2": "dependency-network",
        "3": "oom",
        "4": "runner-timeout",
        "5": "script-error",
    }
    # every finding carries evidence + action
    for p in out["pipelines"]:
        for j in p["failedJobs"]:
            assert j["evidence"] and j["action"]


@pytest.mark.unit
def test_pipeline_failure_rca_oom_beats_generic_markers():
    """OOM markers must win over test/script words in the same trace."""
    job = {"name": "unit", "stage": "test", "status": "failed",
           "failureReason": "script_failure",
           "traceTail": "pytest crashed: exit code 137 (out of memory)"}
    assert ops.classify_job_failure(job)["class"] == "oom"


@pytest.mark.unit
def test_pipeline_failure_rca_falls_back_to_stage_name():
    job = {"name": "integration-tests", "stage": "test", "status": "failed",
           "failureReason": "script_failure", "traceTail": "exited abnormally"}
    finding = ops.classify_job_failure(job)
    assert finding["class"] == "test-failure"
    assert "test" in finding["evidence"]


@pytest.mark.unit
def test_pipeline_failure_rca_counts_classes():
    pipelines = [
        _failed_pipeline("1", [
            {"name": "a", "status": "failed", "traceTail": "connection refused"},
            {"name": "b", "status": "failed", "traceTail": "connection refused"},
        ]),
    ]
    out = ops.pipeline_failure_rca(pipelines)
    assert out["classCounts"] == {"dependency-network": 2}


@pytest.mark.unit
def test_pipeline_failure_rca_empty():
    out = ops.pipeline_failure_rca([])
    assert out["pipelinesEvaluated"] == 0 and out["pipelines"] == []


# ── 2. runner health & queue RCA ─────────────────────────────────────────────


@pytest.mark.unit
def test_runner_health_rca_flags_offline_stale_paused():
    runners = [
        {"id": "1", "description": "healthy", "status": "online", "online": True,
         "paused": False, "tags": ["builder"],
         "contactedAt": "2026-07-17T11:59:00Z"},
        {"id": "2", "description": "gone", "status": "offline", "online": False,
         "paused": False, "tags": ["builder"], "contactedAt": "2026-07-10T00:00:00Z"},
        {"id": "3", "description": "wedged", "status": "online", "online": True,
         "paused": False, "tags": [], "contactedAt": "2026-07-17T10:00:00Z"},  # 2h stale
        {"id": "4", "description": "parked", "status": "paused", "online": True,
         "paused": True, "tags": [], "contactedAt": "2026-07-17T11:59:00Z"},
    ]
    out = ops.runner_health_rca(runners, now=NOW)
    flagged = {r["id"]: r for r in out["flaggedRunners"]}
    assert set(flagged) == {"2", "3", "4"}
    assert "offline" in flagged["2"]["cause"]
    assert "stale" in flagged["3"]["cause"]
    assert "paused" in flagged["4"]["cause"]
    assert flagged["3"]["lastContactMin"] == pytest.approx(120, abs=1)


@pytest.mark.unit
def test_runner_health_rca_queue_and_saturation():
    runners = [
        {"id": "1", "status": "online", "online": True, "paused": False,
         "tags": ["gpu"], "contactedAt": "2026-07-17T11:59:30Z"},
    ]
    queued = [
        {"id": f"j{i}", "name": f"train-{i}", "queuedDurationSec": 900, "tags": ["gpu"]}
        for i in range(3)
    ] + [{"id": "fast", "name": "quick", "queuedDurationSec": 5, "tags": ["gpu"]}]
    out = ops.runner_health_rca(runners, queued_jobs=queued, now=NOW)
    assert len(out["longQueuedJobs"]) == 3  # the 5s job is under threshold
    assert out["saturatedTags"][0]["tag"] == "gpu"
    assert out["saturatedTags"][0]["queuedJobs"] == 3
    assert out["saturatedTags"][0]["onlineRunners"] == 1
    assert out["saturatedTags"][0]["ratio"] == 3.0


@pytest.mark.unit
def test_runner_health_rca_tag_with_no_runners_is_saturated():
    out = ops.runner_health_rca(
        [], queued_jobs=[{"id": "j1", "queuedDurationSec": 999, "tags": ["arm64"]},
                         {"id": "j2", "queuedDurationSec": 999, "tags": ["arm64"]}],
        now=NOW,
    )
    sat = out["saturatedTags"][0]
    assert sat["onlineRunners"] == 0 and sat["ratio"] is None


@pytest.mark.unit
def test_runner_health_rca_healthy_fleet_flags_nothing():
    runners = [{"id": "1", "status": "online", "online": True, "paused": False,
                "tags": ["builder"], "contactedAt": "2026-07-17T11:59:00Z"}]
    out = ops.runner_health_rca(runners, now=NOW)
    assert out["flaggedRunners"] == [] and out["saturatedTags"] == []


# ── 3. artifact/storage bloat ────────────────────────────────────────────────


@pytest.mark.unit
def test_bloat_analysis_ranks_by_total_bytes_and_estimates_reclaim():
    projects = [
        {"path": "dev/small", "repoBytes": 100, "artifactsBytes": 50},
        {"path": "dev/huge", "repoBytes": 10_000, "artifactsBytes": 90_000},
    ]
    artifacts = {
        "dev/huge": [
            # expired two weeks ago but still kept
            {"file": "old.zip", "sizeBytes": 40_000,
             "createdAt": "2026-06-01T00:00:00Z", "expireAt": "2026-07-03T00:00:00Z"},
            # old (46 days) but no expiry set
            {"file": "ancient.zip", "sizeBytes": 20_000,
             "createdAt": "2026-06-01T00:00:00Z", "expireAt": ""},
            # fresh
            {"file": "new.zip", "sizeBytes": 30_000,
             "createdAt": "2026-07-16T00:00:00Z", "expireAt": ""},
        ],
    }
    out = ops.artifact_storage_bloat_analysis(
        projects, artifacts_by_project=artifacts, now=NOW
    )
    assert out["projects"][0]["project"] == "dev/huge"  # biggest first
    huge = out["projects"][0]
    assert huge["expiredButKept"] == 1 and huge["expiredBytes"] == 40_000
    assert huge["olderThanDays"] == 1 and huge["oldBytes"] == 20_000
    assert huge["reclaimableBytes"] == 60_000
    assert out["totalReclaimableBytes"] == 60_000
    assert "delete_artifacts" in huge["action"]


@pytest.mark.unit
def test_bloat_analysis_no_reclaim_message():
    out = ops.artifact_storage_bloat_analysis(
        [{"path": "dev/clean", "repoBytes": 10, "artifactsBytes": 0}], now=NOW
    )
    assert out["projects"][0]["reclaimableBytes"] == 0
    assert "No obvious" in out["projects"][0]["action"]


# ── 4. stale-work audit ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_stale_work_audit_flags_mrs_branches_and_gaps():
    mrs = [
        {"id": "1", "title": "old fix", "state": "opened",
         "updatedAt": "2026-06-01T00:00:00Z", "draft": False},  # 46 days idle
        {"id": "2", "title": "fresh", "state": "opened",
         "updatedAt": "2026-07-16T00:00:00Z", "draft": False},
        {"id": "3", "title": "merged long ago", "state": "merged",
         "updatedAt": "2026-01-01T00:00:00Z", "draft": False},
    ]
    branches = [
        {"name": "main", "default": True, "protected": False,
         "lastCommitAt": "2026-07-17T00:00:00Z"},
        {"name": "dead-feature", "default": False, "protected": False,
         "lastCommitAt": "2025-12-01T00:00:00Z"},  # >90 days
    ]
    protections = [{"branch": "hotfix/*", "allowForcePush": True}]
    out = ops.stale_work_audit(
        mrs, branches, protections=protections, default_branch="main", now=NOW
    )
    assert [m["id"] for m in out["staleMergeRequests"]] == ["1"]
    assert out["staleMergeRequests"][0]["idleDays"] == pytest.approx(46, abs=1)
    assert [b["name"] for b in out["staleBranches"]] == ["dead-feature"]
    gaps = {g["gap"] for g in out["protectionGaps"]}
    assert gaps == {"default-branch-unprotected", "force-push-allowed"}


@pytest.mark.unit
def test_stale_work_audit_protected_default_branch_is_clean():
    branches = [{"name": "main", "default": True, "protected": True,
                 "lastCommitAt": "2026-07-17T00:00:00Z"}]
    out = ops.stale_work_audit(
        [], branches, protections=[{"branch": "main", "allowForcePush": False}],
        default_branch="main", now=NOW,
    )
    assert out["protectionGaps"] == []
    assert out["counts"]["staleBranches"] == 0


@pytest.mark.unit
def test_stale_work_audit_empty():
    out = ops.stale_work_audit([], [], now=NOW)
    assert out["counts"] == {
        "staleMergeRequests": 0, "staleBranches": 0, "protectionGaps": 0,
    }

"""Flagship CI/CD-analysis MCP tools (read-only)."""

from typing import Any, Optional

from cicd_aiops.governance import governed_tool
from cicd_aiops.ops import analysis as ops
from mcp_server._shared import _get_connection, mcp, tool_errors


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def pipeline_failure_rca(
    project: Optional[str] = None,
    limit: int = 10,
    tail_lines: int = 60,
    failed_pipelines: Optional[list[dict[str, Any]]] = None,
    target: Optional[str] = None,
) -> dict:
    """[READ] Classify recent failed pipelines: cause + action per pipeline.

    The flagship pipeline RCA: pulls the project's recent failed pipelines with
    their failed jobs and trace tails, classifies each failed job (test-failure /
    dependency-network / runner-timeout / oom / script-error) from its
    failure_reason and trace markers, and attaches a cause and a recommended
    action. Every classification names its matched evidence, not a black-box
    verdict. Pass 'failed_pipelines' for pure analysis, or a project to pull live.

    Args:
        project: Project id or full path (required unless failed_pipelines given).
        limit: How many recent failed pipelines to pull (default 10).
        tail_lines: Trace-tail lines pulled per failed job (default 60).
        failed_pipelines: Injected rows {id, ref, jobs:[{name, stage, status,
            failureReason, traceTail}]}; skips the live pull.
        target: Server target name from config; omit for the default.

    Returns dict: {pipelinesEvaluated, classCounts, pipelines:[{pipeline, ref,
        headlineClass, cause, action, failedJobs:[{job, stage, class, cause,
        action, evidence}]}], note}.
    """
    if failed_pipelines is None:
        if not project:
            raise ValueError("Pass a 'project' (or inject 'failed_pipelines').")
        failed_pipelines = ops.pull_failed_pipelines(
            _get_connection(target), project, limit=limit, tail_lines=tail_lines
        )
    return ops.pipeline_failure_rca(failed_pipelines)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def runner_health_rca(
    stale_contact_min: float = 30.0,
    queue_sec: float = 300.0,
    saturation_ratio: float = 2.0,
    runners: Optional[list[dict[str, Any]]] = None,
    queued_jobs: Optional[list[dict[str, Any]]] = None,
    target: Optional[str] = None,
) -> dict:
    """[READ] Flag offline/stale/paused runners, long-queued jobs, tag saturation.

    The flagship capacity RCA: pulls the runner fleet, flags each runner that is
    offline, stale (no contact for stale_contact_min minutes) or paused, lists
    jobs queued past queue_sec, and computes per-tag saturation (queued jobs vs
    online unpaused runners). Every flag carries its numbers. Pass 'runners' /
    'queued_jobs' for pure analysis, or a target to pull the fleet live.

    Args:
        stale_contact_min: Minutes since last contact at which a runner is stale.
        queue_sec: Seconds a job may wait before being flagged (default 300).
        saturation_ratio: Flagged queued jobs per online runner at which a tag
            is saturated (default 2.0).
        runners: Injected rows {id, description, status, paused, online, tags,
            contactedAt}; skips the live pull.
        queued_jobs: Injected rows {id, name, queuedDurationSec, createdAt, tags}.
        target: Server target name from config; omit for the default.

    Returns dict: {runnersEvaluated, flaggedRunners, longQueuedJobs,
        saturatedTags, thresholds, note}.
    """
    if runners is None:
        from cicd_aiops.ops import runners as runner_ops

        runners = runner_ops.pull_runners(_get_connection(target))
    return ops.runner_health_rca(
        runners,
        queued_jobs=queued_jobs,
        stale_contact_min=stale_contact_min,
        queue_sec=queue_sec,
        saturation_ratio=saturation_ratio,
    )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def artifact_storage_bloat_analysis(
    old_artifact_days: float = 30.0,
    limit: int = 100,
    projects: Optional[list[dict[str, Any]]] = None,
    artifacts_by_project: Optional[dict[str, list[dict[str, Any]]]] = None,
    target: Optional[str] = None,
) -> dict:
    """[READ] Rank projects by storage; estimate reclaimable artifact bytes.

    The flagship storage RCA: pulls project storage statistics, ranks projects
    by repo + artifact bytes, counts expired-but-kept artifacts and artifacts
    older than old_artifact_days, and estimates the reclaimable bytes per
    project. Every ranking carries its byte numbers. Pass 'projects' (and
    optionally 'artifacts_by_project') for pure analysis, or a target to pull
    live.

    Args:
        old_artifact_days: Age in days past which a kept artifact counts as
            reclaimable (default 30).
        limit: How many projects to pull when live (default 100).
        projects: Injected rows {path, repoBytes, artifactsBytes}; skips the
            live pull.
        artifacts_by_project: Injected map {project: [{file, sizeBytes,
            createdAt, expireAt}]}.
        target: Server target name from config; omit for the default.

    Returns dict: {projectsEvaluated, totalReclaimableBytes, thresholds,
        projects:[{project, repoBytes, artifactsBytes, totalBytes,
        expiredButKept, reclaimableBytes, action}], note}.
    """
    if projects is None:
        from cicd_aiops.ops import projects as project_ops

        projects = project_ops.pull_projects_with_stats(_get_connection(target), limit=limit)
    return ops.artifact_storage_bloat_analysis(
        projects,
        artifacts_by_project=artifacts_by_project,
        old_artifact_days=old_artifact_days,
    )


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def stale_work_audit(
    project: Optional[str] = None,
    stale_mr_days: float = 14.0,
    stale_branch_days: float = 90.0,
    merge_requests: Optional[list[dict[str, Any]]] = None,
    branches: Optional[list[dict[str, Any]]] = None,
    protections: Optional[list[dict[str, Any]]] = None,
    default_branch: str = "",
    target: Optional[str] = None,
) -> dict:
    """[READ] Long-open MRs/PRs, inactive branches, protection config gaps.

    The flagship hygiene audit: flags open merge/pull requests idle past
    stale_mr_days, non-default branches with no commit for stale_branch_days,
    a default branch without protection, and protection rules that allow
    force-push. Every flag carries its numbers. Pass injected rows for pure
    analysis, or a project to pull live.

    Args:
        project: Project id or full path (required unless rows are injected).
        stale_mr_days: Days an open MR may idle before flagging (default 14).
        stale_branch_days: Days a branch may idle before flagging (default 90).
        merge_requests: Injected rows {id, title, state, updatedAt, draft}.
        branches: Injected rows {name, default, protected, lastCommitAt}.
        protections: Injected rows {branch, allowForcePush}.
        default_branch: Default-branch name (pulled live when omitted).
        target: Server target name from config; omit for the default.

    Returns dict: {staleMergeRequests, staleBranches, protectionGaps, counts,
        thresholds, note}.
    """
    if merge_requests is None or branches is None:
        if not project:
            raise ValueError(
                "Pass a 'project' (or inject 'merge_requests' and 'branches')."
            )
        from cicd_aiops.ops import projects as project_ops
        from cicd_aiops.ops import repos as repo_ops

        conn = _get_connection(target)
        if merge_requests is None:
            pulled = repo_ops.list_merge_requests(conn, project)
            merge_requests = pulled.get("mergeRequests", []) if isinstance(pulled, dict) else []
        if branches is None:
            pulled = repo_ops.list_branches(conn, project)
            branches = pulled.get("branches", []) if isinstance(pulled, dict) else []
        if protections is None:
            pulled = repo_ops.list_protected_branches(conn, project)
            protections = pulled.get("protections", []) if isinstance(pulled, dict) else []
        if not default_branch:
            detail = project_ops.project_detail(conn, project)
            default_branch = detail.get("defaultBranch", "") if isinstance(detail, dict) else ""
    return ops.stale_work_audit(
        merge_requests,
        branches,
        protections=protections,
        default_branch=default_branch,
        stale_mr_days=stale_mr_days,
        stale_branch_days=stale_branch_days,
    )

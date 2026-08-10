"""Read-path ops tests (server / projects / pipelines / runners / repos / artifacts).

Uses a fake connection that returns canned JSON per path, so the cross-platform
normalisation is exercised without a live GitLab/Gitea. The fake carries a real
Platform descriptor so ops resolve the same paths they would in production.
"""

import pytest

from cicd_aiops.config import TargetConfig
from cicd_aiops.ops import artifacts, overview, pipelines, projects, repos, runners, server
from cicd_aiops.platform import GITEA, GITLAB


class _Conn:
    """Fake connection: get() looks up canned responses by path."""

    def __init__(self, responses, platform=GITLAB):
        self.target = TargetConfig(name="t", platform=platform, base_url="https://h")
        self.platform = self.target.platform_obj
        self._responses = responses

    def get(self, path, **_kw):
        return self._responses.get(path, {})


def _p(platform, resource, **fmt):
    from cicd_aiops.platform import get_platform

    return get_platform(platform).path(resource, **fmt)


# ── server ──────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_server_version_normalizes():
    conn = _Conn({_p(GITLAB, "version"): {"version": "17.2.1", "revision": "abc123"}})
    out = server.server_version(conn)
    assert out["version"] == "17.2.1" and out["platform"] == "gitlab"


@pytest.mark.unit
def test_current_user_scope_probe_both_shapes():
    gl = _Conn({_p(GITLAB, "current_user"): {"username": "ops-bot", "is_admin": True}})
    assert server.current_user(gl)["username"] == "ops-bot"
    assert server.current_user(gl)["isAdmin"] is True
    gt = _Conn(
        {_p(GITEA, "current_user"): {"login": "gitea-bot", "full_name": "Bot"}},
        platform=GITEA,
    )
    assert server.current_user(gt)["username"] == "gitea-bot"


# ── projects ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_list_projects_gitlab_statistics():
    # Model GitLab's REAL project shape: it has a `name` (display name) distinct
    # from `path`/`path_with_namespace`, and integer byte statistics. A live
    # GitLab 19.2 exposed both gaps the earlier fixture (no `name`) could not.
    conn = _Conn({
        _p(GITLAB, "projects"): [
            {"id": 1, "name": "api", "path": "api", "path_with_namespace": "dev/api",
             "default_branch": "main",
             "statistics": {"repository_size": 1000, "job_artifacts_size": 500,
                            "storage_size": 1500}},
        ]
    })
    out = projects.list_projects(conn)
    assert out["returned"] == 1
    p = out["projects"][0]
    assert p["name"] == "api", "the human display name must be surfaced, not just the path"
    assert p["path"] == "dev/api"
    assert p["repoBytes"] == 1000 and p["artifactsBytes"] == 500
    # Byte counts are integers — equality passes for 1000.0 too, so assert the type.
    assert isinstance(p["repoBytes"], int) and isinstance(p["artifactsBytes"], int)
    assert isinstance(p["storageBytes"], int)


@pytest.mark.unit
def test_list_projects_gitea_search_shape():
    conn = _Conn(
        {_p(GITEA, "projects"): {"data": [
            {"id": 7, "name": "web", "full_name": "dev/web", "default_branch": "main",
             "size": 2},
        ]}},
        platform=GITEA,
    )
    out = projects.list_projects(conn)
    assert out["returned"] == 1
    p = out["projects"][0]
    assert p["name"] == "web"
    # Gitea reports size in KiB → bytes, as an integer
    assert p["repoBytes"] == 2048 and isinstance(p["repoBytes"], int)


# ── pipelines ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_list_pipelines_gitlab_shape():
    conn = _Conn({
        _p(GITLAB, "pipelines", project="1"): [
            {"id": 11, "status": "failed", "ref": "main", "sha": "deadbeef"},
            {"id": 10, "status": "success", "ref": "main", "sha": "cafe"},
        ]
    })
    out = pipelines.list_pipelines(conn, "1")
    assert out["returned"] == 2
    assert out["pipelines"][0]["status"] == "failed"


@pytest.mark.unit
def test_list_pipelines_on_gitea_reports_the_missing_resource():
    """Gitea API v1 exposes no pipeline-run listing — say so, do not 404.

    This test previously asserted that a `workflow_runs` payload came back from
    `/actions/runs`, a path that does not exist on any Gitea (confirmed against
    1.24.7's own swagger.v1.json). Every pipeline call therefore 404'd on a real
    server while the mock stayed green. The row-level `workflow_runs` unwrapping
    is still exercised through the `jobs` resource, which is the real endpoint.
    """
    conn = _Conn({}, platform=GITEA)
    out = pipelines.list_pipelines(conn, "dev/web")
    assert "not available on platform 'gitea'" in out["error"]
    assert out["project"] == "dev/web"


@pytest.mark.unit
def test_list_jobs_gitea_workflow_runs_shape():
    """Gitea's `/actions/tasks` wraps its rows under `workflow_runs`."""
    conn = _Conn(
        {_p(GITEA, "jobs", project="dev/web"): {"workflow_runs": [
            {"id": 3, "status": "failure", "head_branch": "main", "head_sha": "aa"},
        ]}},
        platform=GITEA,
    )
    rows = conn.platform.rows(conn.get(conn.platform.path("jobs", project="dev/web")))
    assert len(rows) == 1 and rows[0]["head_branch"] == "main"


@pytest.mark.unit
def test_pipeline_jobs_normalizes_failure_reason_and_tags():
    conn = _Conn({
        _p(GITLAB, "pipeline_jobs", project="1", pipeline="11"): [
            {"id": 100, "name": "unit-tests", "stage": "test", "status": "failed",
             "failure_reason": "script_failure", "tag_list": ["builder", "x86"],
             "queued_duration": 4.2},
        ]
    })
    out = pipelines.pipeline_jobs(conn, "1", "11")
    job = out["jobs"][0]
    assert job["failureReason"] == "script_failure"
    assert job["tags"] == ["builder", "x86"]
    assert job["queuedDurationSec"] == 4.2


@pytest.mark.unit
def test_job_trace_tail_returns_last_lines():
    trace = "\n".join(f"line{i}" for i in range(200))
    conn = _Conn({_p(GITLAB, "job_trace", project="1", job="100"): trace})
    out = pipelines.job_trace_tail(conn, "1", "100", tail_lines=5)
    assert out["totalLines"] == 200 and out["tailLines"] == 5
    assert "line199" in out["trace"] and "line193" not in out["trace"]


# ── runners ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_list_runners_sorts_offline_first():
    conn = _Conn({
        _p(GITLAB, "runners"): [
            {"id": 1, "description": "ok", "status": "online", "online": True,
             "paused": False},
            {"id": 2, "description": "dead", "status": "offline", "online": False,
             "paused": False},
        ]
    })
    out = runners.list_runners(conn)
    assert out["returned"] == 2
    assert out["runners"][0]["description"] == "dead"


@pytest.mark.unit
def test_runners_on_gitea_raise_teaching_error():
    conn = _Conn({}, platform=GITEA)
    with pytest.raises(KeyError, match="not available on platform 'gitea'"):
        runners.list_runners(conn)


# ── repo surface ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_list_merge_requests_normalizes_both_shapes():
    gl = _Conn({
        _p(GITLAB, "merge_requests", project="1"): [
            {"iid": 5, "title": "Fix", "state": "opened", "draft": False,
             "author": {"username": "alice"}, "source_branch": "fix",
             "target_branch": "main", "updated_at": "2026-07-01T00:00:00Z"},
        ]
    })
    out = repos.list_merge_requests(gl, "1")
    mr = out["mergeRequests"][0]
    assert mr["author"] == "alice" and mr["sourceBranch"] == "fix"

    gt = _Conn(
        {_p(GITEA, "merge_requests", project="dev/web"): [
            {"number": 9, "title": "Add", "state": "open",
             "user": {"login": "bob"},
             "head": {"ref": "feat"}, "base": {"ref": "main"}},
        ]},
        platform=GITEA,
    )
    out = repos.list_merge_requests(gt, "dev/web")
    mr = out["mergeRequests"][0]
    assert mr["id"] == "9" and mr["author"] == "bob"
    assert mr["sourceBranch"] == "feat" and mr["targetBranch"] == "main"


@pytest.mark.unit
def test_list_branches_reads_commit_dates():
    conn = _Conn({
        _p(GITLAB, "branches", project="1"): [
            {"name": "main", "default": True, "protected": True,
             "commit": {"committed_date": "2026-07-01T00:00:00Z"}},
            {"name": "old", "default": False, "protected": False,
             "commit": {"committed_date": "2025-01-01T00:00:00Z"}},
        ]
    })
    out = repos.list_branches(conn, "1")
    assert out["returned"] == 2
    assert out["branches"][0]["default"] is True
    assert out["branches"][1]["lastCommitAt"].startswith("2025-01-01")


@pytest.mark.unit
def test_list_protected_branches_force_push_flags():
    gl = _Conn({
        _p(GITLAB, "protected_branches", project="1"): [
            {"name": "main", "allow_force_push": False},
            {"name": "hotfix/*", "allow_force_push": True},
        ]
    })
    out = repos.list_protected_branches(gl, "1")
    assert out["protections"][0]["allowForcePush"] is False
    assert out["protections"][1]["allowForcePush"] is True

    gt = _Conn(
        {_p(GITEA, "protected_branches", project="dev/web"): [
            {"branch_name": "main", "enable_force_push": True},
        ]},
        platform=GITEA,
    )
    out = repos.list_protected_branches(gt, "dev/web")
    assert out["protections"][0]["branch"] == "main"
    assert out["protections"][0]["allowForcePush"] is True


@pytest.mark.unit
def test_list_releases_normalizes():
    conn = _Conn({
        _p(GITLAB, "releases", project="1"): [
            {"tag_name": "v1.2.0", "name": "v1.2.0", "created_at": "2026-06-01T00:00:00Z"},
        ]
    })
    out = repos.list_releases(conn, "1")
    assert out["releases"][0]["tag"] == "v1.2.0"


# ── artifacts ───────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_list_artifacts_gitlab_flattens_job_files_and_counts_expired():
    conn = _Conn({
        _p(GITLAB, "jobs", project="1"): [
            {"id": 100, "name": "build",
             "artifacts": [{"filename": "app.zip", "size": 1000},
                           {"filename": "trace.log", "size": 10}],
             "artifacts_expire_at": "2026-01-01T00:00:00Z",  # already past
             "finished_at": "2025-12-31T00:00:00Z"},
            {"id": 101, "name": "test", "artifacts": [], "finished_at": None},
        ]
    })
    out = artifacts.list_artifacts(conn, "1")
    assert out["returned"] == 2
    assert out["totalBytes"] == 1010
    assert out["expiredButKept"] == 2  # both files ride the expired job


@pytest.mark.unit
def test_list_artifacts_gitea_actions_shape():
    conn = _Conn(
        {_p(GITEA, "artifacts", project="dev/web"): {"artifacts": [
            {"name": "dist", "size_in_bytes": 2048, "created_at": "2026-07-01T00:00:00Z"},
        ]}},
        platform=GITEA,
    )
    out = artifacts.list_artifacts(conn, "dev/web")
    assert out["returned"] == 1 and out["totalBytes"] == 2048


# ── overview ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_cicd_overview_resilient_shapes():
    conn = _Conn({
        _p(GITLAB, "version"): {"version": "17.2.1"},
        _p(GITLAB, "current_user"): {"username": "ops-bot"},
        _p(GITLAB, "projects"): [{"id": 1, "path_with_namespace": "dev/api"}],
        _p(GITLAB, "runners"): [
            {"id": 1, "online": True, "status": "online"},
            {"id": 2, "online": False, "status": "offline"},
        ],
    })
    out = overview.cicd_overview(conn)
    assert out["platform"] == "gitlab"
    assert out["version"] == "17.2.1"
    assert out["authenticatedAs"] == "ops-bot"
    assert out["projectsTotal"] == 1
    assert out["runnersOnline"] == 1 and out["runnersTotal"] == 2


@pytest.mark.unit
def test_cicd_overview_gitea_skips_runner_surface():
    conn = _Conn(
        {
            _p(GITEA, "version"): {"version": "1.24.0"},
            _p(GITEA, "current_user"): {"login": "gitea-bot"},
            _p(GITEA, "projects"): {"data": [{"id": 1, "full_name": "dev/web"}]},
        },
        platform=GITEA,
    )
    out = overview.cicd_overview(conn)
    assert out["runnersTotal"] is None  # unsupported surface, not an error
    assert out["errors"] == []

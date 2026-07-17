# Changelog

## v0.1.1 — 2026-07-17

### Fixed
- Added the MCP Registry ownership marker (mcp-name) to the README so the server publishes to the MCP Registry.

## v0.1.0 — 2026-07-17

Initial preview release.

- **Platforms**: self-managed GitLab (REST API v4, `PRIVATE-TOKEN`) and
  self-hosted Gitea (API v1, `Authorization: token`) behind a name-keyed
  platform registry; unsupported surfaces raise teaching errors.
- **Reads (16)**: server version + token identity + overview; projects with
  storage statistics; pipelines/runs, jobs, trace tails; runner fleet
  (GitLab); merge/pull requests, branches, protection rules, releases;
  artifact inventories with expiry.
- **Flagship analyses (4)**: `pipeline_failure_rca` (test-failure /
  dependency-network / runner-timeout / oom / script-error with evidence),
  `runner_health_rca` (offline/stale/paused, queue waits, tag saturation),
  `artifact_storage_bloat_analysis` (ranked storage + reclaimable bytes),
  `stale_work_audit` (idle MRs/branches, protection gaps).
- **Governed writes (6)**: `retry_pipeline` / `cancel_pipeline` (priorState
  status), `pause_runner` / `resume_runner` (reversible undo pair),
  `delete_artifacts` (risk=high, priorState bytes/count, irreversible),
  `update_branch_protection` (undo replays prior settings). All with
  `dry_run` previews; CLI writes double-confirm and run through the governed
  path (audited).
- **Governance harness** bundled: audit (`~/.cicd-aiops/audit.db`), policy
  engine with secure-by-default dual-control for high risk, token/runaway
  budgets, undo store, injection-safe output sanitisation.
- **Secrets**: encrypted store (`secrets.enc`, Fernet + scrypt), `init`
  wizard, `secret` commands; TLS verification defaults ON.
- 114 tests, mock-only (no live server validation yet).

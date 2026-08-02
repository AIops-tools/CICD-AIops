# Changelog

## Unreleased — 2026-08-02

### Changed (BREAKING)
- **Requires MCP SDK 2.0** (`mcp[cli]>=2.0,<3.0`). `mcp.server.fastmcp` no longer exists in 2.0; the server is now built with `MCPServer` and reports its package version in the stdio handshake.

### Fixed
- **`undo apply` works from the CLI.** Every write tool is imported lazily inside its own CLI command, so a CLI-driven undo ran in a process where the inverse tool was never registered and failed with "inverse tool is not registered" — for every write tool. Only the MCP entry point, which imports the whole server, worked. Found while live-verifying against a real cluster.
- **An undetermined outcome is audited `unknown`, not `ok`.** The harness only classified a result as undetermined when the payload *also* carried an `error` key, so a write that looked successful but had not been confirmed was recorded as a success.
- **`as_int` no longer round-trips integers through float64**, which cannot represent values above 2**53 exactly. A line-wide sweep found only one of six vendored copies had actually been fixed after the original precision bug. The bool guard precedes the int short-circuit because `bool` subclasses `int` — otherwise `True` would be returned unchanged and serialised as `true` rather than a number.


## v0.5.0 — 2026-07-21

### Fixed
- `list_projects` surfaces each project's `name` and reports byte counts as integers (was float) — found live against real GitLab CE 19.2.

See RELEASE_NOTES.md for detail.


## v0.4.0 — 2026-07-21

### Changed (BREAKING)
- **Removed the authorization layer** — read-only mode, the approver gate, and rules.yaml deny are gone. The skill no longer decides read vs write; that is the agent's judgement or the connecting account's permissions. `<PREFIX>_READ_ONLY` now has no effect (a startup warning is logged); `<PREFIX>_AUDIT_APPROVED_BY`/`_RATIONALE` are optional audit annotations.
- The retained guarantee is **unbypassable audit over MCP and CLI alike** — no unaudited entry point. Harness = audit + runaway safety guard + undo + sanitize; `risk_level` is a descriptive audit label, not a gate.

See RELEASE_NOTES.md for tool-specific changes.


## v0.3.0 — 2026-07-20

### Fixed
- Harness: a write whose response is lost is audited `status=unknown`, not `error` — it may have taken effect. Undo tokens gain `effectVerified` (undo.db migrated in place).
- Harness: a dry-run no longer records an undo token, and no longer requires a named approver. Guards now run on the preview path.
- Truncated strings end in an ellipsis instead of being cut silently; error messages are capped at 800 chars, not 300.

See RELEASE_NOTES.md for the full detail.

## v0.1.2 — 2026-07-17

### Fixed
- runner_health_rca live-pull path called a nonexistent ops.analysis.pull_runners; now dispatches to ops.runners.pull_runners (the RCA raised AttributeError on live data before).

### Tests
- Coverage raised to ~91% (governance harness + ops/CLI/connection layers).

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

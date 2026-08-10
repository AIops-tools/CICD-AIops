# Changelog

## v0.9.0 — 2026-08-10

### Fixed
- **`delete_artifacts` reported an irreversible destruction that had not happened** (bug class #13 — submitted is not completed). GitLab answers the project-wide bulk delete with **202 Accepted**: it queues the work and later removes only the artifacts it considers *eligible*, keeping locked ones. The tool treated the call as done, returned `priorState` as "what was destroyed", and the audit row said `ok`. Measured on GitLab 19.2.1: 202 came back, and **100 seconds later all seven artifacts were still present** — an audit trail asserting a deletion that never occurred, which is the worst shape this defect can take. The bulk path now returns `outcomeUnknown`, reports the figure as `inventoryAtRequest` (an upper bound, not a receipt), explains that the server decides eligibility, and the CLI exits 2. The per-job path is genuinely synchronous — verified removing real artifacts — and still reports a confirmed result.
- **The per-job delete over-counted what it destroyed.** A job's log is listed among its artifacts but is *not* removed by that endpoint: after a real delete, every `job.log` (`file_type: "trace"`) was still there while `priorState` claimed all seven files were gone. Traces are now excluded from the destroyed count, and `fileType` is carried on every artifact row so a caller can tell them apart.
- **The dry-run of that HIGH-risk delete could never say how many artifacts it would remove.** It read `currentCount` from the inventory's `total` key — a key the listing envelope deliberately does not have — so the one number an operator needs before an irreversible deletion was always `null`. It now reads `artifactsFound`, which counts every artifact found rather than just the returned page.
- **Artifact sizes are integers** (bug class #2). `sizeBytes` and `totalBytes` rendered as floats (`374.0`) although GitLab reports ints; the storage RCA's byte totals had the same defect from `0.0` accumulator seeds. An earlier round fixed only the write path and the changelog implied the whole surface — the read path was still wrong.
- **The CLI exits 2 on an undetermined outcome**, matching the rest of the line: `emit_governed` only knew about `{"error": ...}`, so a queued-but-unconfirmed write exited 0.

## v0.8.0 — 2026-08-10

### Fixed
- **The entire pipeline surface was broken on Gitea.** `pipelines`, `pipeline` and `pipeline_jobs` were mapped to `/api/v1/repos/{project}/actions/runs` and its children — paths that **do not exist on any Gitea** (confirmed against 1.24.7's own `swagger.v1.json`, where the only `/actions/runs/...` path is `/{run}/artifacts`). Every pipeline call 404'd on a real server. Gitea API v1 has no run-level resource — `/actions/tasks` is the per-**job** listing, whose rows share a `run_number` despite the payload calling them `workflow_runs` — so the three keys are now unmapped and raise the teaching `UnsupportedResource` error naming what the platform does offer.
- **The pipeline RCA reported a healthy zero while it could not look.** `rca pipelines` returned `pipelinesEvaluated: 0` with an empty list on a server holding a genuinely failed job, because the failed listing came back as an `{"error": ...}` envelope and `.get("pipelines", [])` read it as "none". A probe that never ran must not be summarised as health: `pull_failed_pipelines` now raises `PipelineProbeFailed` with the underlying reason.
- **Governed writes exited 0 when they failed.** All 12 CLI write call sites printed the governed payload without inspecting it, so a rejected or failed write — `artifacts delete` refusing on Gitea, for instance — was reported on stdout with exit code 0, and no script could tell it had not happened. They now go through `emit_governed`, which mirrors the error handling `dry_run_preview` already applied to previews. The same defect class was fixed earlier in the proxmox / xcpng / veeam / truenas siblings; this repo had not been swept.
- **`delete_artifacts` reports the destroyed byte total as an int, not a float** (bug class #2). `priorState.bytes` summed `sizeBytes` through the float helper `num()`, so a byte count came back as e.g. `300.0` — arithmetically right, semantically wrong. Now uses `as_int`; a regression test asserts the type (equality cannot catch `300 == 300.0`). Found by enumerating the write path across the line after the same defect surfaced in queue-aiops's `kill_client`.

## v0.7.0 — 2026-08-03

### Fixed
- **`undo apply` replays against the target the original write ran on.** It dispatched the inverse against whatever target the *caller* named — in practice the config's first entry — while the write's own target sat unused in the undo record. On a multi-target config the inverse therefore ran against the wrong host; it only looks harmless because the resource usually is not there, but two hosts holding the same name and the inverse **succeeds on the wrong one, silently**. An explicitly named target still wins. Line-wide: all 24 copies had the identical defect. Caught live in container-host-aiops, where a stop recorded against a Podman target replayed against a Portainer one.

## v0.6.0 — 2026-08-02

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

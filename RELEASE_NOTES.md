# cicd-aiops v0.1.0 — release notes

First preview of **cicd-aiops**: governed AI-ops for self-managed GitLab and
self-hosted Gitea CI/CD servers.

## Highlights

- **26 governed MCP tools** (20 reads incl. 4 flagship RCAs, 6 writes), every
  one wrapped with the bundled audit / budget / risk-tier / undo harness.
- **Pipeline-failure RCA**: failed jobs classified from failure_reason +
  trace-tail markers — test-failure, dependency/network, runner-timeout, OOM,
  script error — each with matched evidence, cause, and action.
- **Runner health & queue RCA**: offline/stale/paused runners, long-queued
  jobs, per-tag saturation.
- **Artifact/storage bloat**: projects ranked by repo + artifact bytes,
  expired-but-kept artifacts, reclaimable estimate → feeds
  `delete_artifacts --dry-run`.
- **Stale-work audit**: idle MRs/branches and protection gaps (unprotected
  default branch, force-push allowed).
- **Writes with faithful before-state**: pause/resume runner is a true undo
  pair; branch protection undo replays prior settings; pipeline retry/cancel
  and artifact deletion record priorState (irreversible, artifact deletion is
  risk=high behind the approver gate).
- **Encrypted secrets** (Fernet + scrypt), TLS verify default ON, friendly
  `init` wizard, `doctor` with version + token-scope probes.

## Known limits (v0.1)

- Preview / mock-only: modelled from public API docs, exercised against
  mocked HTTP; not yet validated on live servers.
- Runner administration, pipeline retry/cancel, and artifact deletion are
  GitLab surfaces; on Gitea they raise a teaching error (no API v1
  equivalent).
- Self-managed instances only — GitLab.com / Gitea Cloud are out of scope.

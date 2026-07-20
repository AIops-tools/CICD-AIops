# Live verification status

This document records what has and has not been validated against real CI
servers, so the maturity claim is auditable rather than a vibe.

## Already live-verified ✅ — Gitea 1.27.0 (2026-07-20)

- `doctor` against a live server: version detected, **token scope probe** confirmed
  the credential actually authenticates (`authenticated as 'aiops'`).
- Reads cross-checked against Gitea's own API: `overview`, `projects` (repo count
  matched `/api/v1/repos/search` exactly, with the truncation envelope present),
  `pipelines list`, `artifacts list`.
- RCA: `rca pipelines`, `rca stale`, `rca storage` all ran against the live server.
- **Platform registry behaves as designed**: GitLab-only resources fail fast on
  Gitea with a message naming every resource the platform *does* expose, rather
  than silently returning nothing.

**A real bug was found and fixed by this run**: that fail-fast message was being
reported by the CLI as `Error: Missing required key or environment variable: "..."`.
The correct explanation was inside the quotes, but the headline sent the reader
hunting a config/env problem that did not exist. Unsupported resources now raise a
dedicated `UnsupportedResource` (a `KeyError` subclass, so existing handlers keep
working) and the CLI reports it as what it is. `proxy-aiops` already had this
pattern right — this repo had diverged from it.

## Not yet live-verified ⚠️

- **GitLab** — the entire GitLab platform branch, which is the richer of the two
  (runners, job traces, artifact retention). This is now the largest gap here.
- **Actual pipeline runs**: the verified Gitea instance had Actions disabled with no
  runner attached, so pipeline-failure RCA had no real failed jobs to classify.
- **Guarded writes** (`pipelines retry/cancel`, `runners pause/resume`,
  `artifacts delete`) and their undo paths.

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

- ~~**GitLab** — the entire GitLab platform branch, which is the richer of the two~~
  **Closed 2026-08-03 against a real GitLab CE 19.2.1 with a registered runner.
  No defects found.** Recorded because a clean result is evidence too:
  - `doctor` reported the version, the authenticated identity, and a token-scope
    probe; `overview` and `runners list` matched the server, with the truncation
    envelope and the `runnersSupported` note intact.
  - **A pipeline that genuinely failed** — a shell-executor runner registered to
    the project, a job running `exit 7`, GitLab recording
    `failure_reason: script_failure`. `rca pipelines` classified both failed
    pipelines and, importantly, reported the *evidence* it used.
  - **Governed writes closed the loop**: `runners pause` → the server reports
    `paused: true` → `undo apply` → `resume_runner`, `effectVerified: true` →
    the server reports `paused: false`. `pipelines retry` re-ran the job (which
    failed again, correctly) and recorded **no** undo, which is right — a retry
    has no inverse.

> **One thing examined and deliberately left alone.** With no trace marker, a
> job in a stage named `test` is classified `test-failure` from the stage name
> even though GitLab supplied `failure_reason: script_failure`. That looks like
> the server's own attribution losing to a name guess — but on GitLab a real
> test failure *also* reports `script_failure` (the script exits non-zero
> either way), so the field does not discriminate and the stage name is genuine
> extra signal. The classifier records `evidence: job/stage name contains
> 'test'`, so the basis is auditable. Changing this would make the common case
> worse; it is not a defect.
- ~~**Actual pipeline runs**~~ — **closed 2026-08-03 on the GitLab side**: a
  registered runner executed a job that really failed, so the RCA classified
  real failures rather than an empty list. The **Gitea** side still has no
  runner attached.
- **Guarded writes** (`pipelines retry/cancel`, `runners pause/resume`,
  `artifacts delete`) and their undo paths.

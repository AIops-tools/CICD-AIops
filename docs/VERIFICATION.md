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
- **Guarded writes on GitLab** — `runners pause/resume` (with undo) and
  `pipelines retry` were closed on 2026-08-03; `pipelines cancel` and
  `artifacts delete` against a live GitLab are still open. The
  `delete_artifacts` byte-total fix shipped in this round is **unit-tested
  only** — it was found by enumerating the write path across the line, not by a
  live run.

## Gitea — live-verified 2026-08-10 (Gitea 1.24.7 + act_runner v0.6.1)

A real repository, a registered runner, and a workflow whose jobs genuinely
ran: `build` succeeded and `failing-test` exited 7. `doctor` reported the
version and authenticated identity; `overview` and `projects` matched the
server. **Three defects, two of them serious:**

- 🔴 **The whole pipeline surface had never worked on Gitea.** `pipelines`,
  `pipeline` and `pipeline_jobs` were mapped to `/api/v1/repos/{p}/actions/runs`
  and its children — **paths that do not exist**. Confirmed against the
  server's own `swagger.v1.json`: the only `/actions/runs/...` path is
  `/{run}/artifacts`, and the real listing is `/actions/tasks`, whose rows are
  individual **jobs** sharing a `run_number` (despite the payload naming them
  `workflow_runs`). Gitea API v1 has no run-level resource at all, so the three
  keys are now unmapped and raise the repo's own `UnsupportedResource` teaching
  error instead of a 404 nobody can act on.
- 🔴 **The pipeline RCA reported a clean zero while it could not look.**
  `rca pipelines` returned `pipelinesEvaluated: 0, pipelines: []` — a confident
  "nothing is failing" — on a server that held a genuinely failed job, because
  the 404 came back as an `{"error": ...}` envelope and
  `.get("pipelines", [])` read it as empty. That is bug class #3: a failure
  presented as health. `pull_failed_pipelines` now raises `PipelineProbeFailed`,
  so the RCA reports why it could not look.
- 🔴 **Every governed write exited 0 on failure.** All 12 CLI write call sites
  printed the governed payload without checking it, so `artifacts delete`
  printed "Resource 'artifacts_delete' is not available on platform 'gitea'"
  and still exited 0 — a script could not tell the write had not happened. The
  same class was already fixed in the proxmox / xcpng / veeam / truenas
  siblings; this repo had not been swept. Now routed through `emit_governed`,
  which mirrors what `dry_run_preview` already did for previews. Verified live:
  exit 1 on a refused write, 0 on a successful read.

**What Gitea genuinely cannot do, and is now reported as such**: instance-wide
runner listing (the API is repo/org/user-scoped only — there is no admin runner
endpoint) and bulk artifact deletion (only `DELETE .../artifacts/{id}` exists).

**Not verified, with a measured reason**: `delete_artifacts` could not be
exercised here because Gitea's artifact API stayed empty — `upload-artifact@v3`
reported success (200003 bytes) yet neither `/actions/artifacts` nor
`/actions/runs/{run}/artifacts` ever listed it, and `@v4` fails outright on
act_runner v0.6.1. That is a Gitea/act_runner limitation, not a tool defect.

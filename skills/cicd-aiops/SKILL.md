---
name: cicd-aiops
description: >
  Use this skill whenever the user needs to operate a self-managed GitLab or self-hosted Gitea CI/CD server — a one-shot overview, server version and token identity, projects with storage statistics, pipelines/runs with jobs and trace tails, the runner fleet, merge/pull requests, branches, protection rules and releases, artifact inventories, four flagship RCAs (pipeline failures, runner health & queue, artifact/storage bloat, stale work), and governed writes (retry/cancel a pipeline, pause/resume a runner, delete artifacts, update branch protection).
  Always use this skill for "GitLab", "Gitea", "pipeline failed", "CI is red", "job trace", "runner offline", "jobs stuck in queue", "artifact storage full", "stale merge requests", "stale branches", "protect the default branch", "retry the pipeline", "cancel the pipeline", "delete old artifacts" when the context is a self-managed GitLab or Gitea instance.
  Do NOT use when the target is something other than a GitLab/Gitea CI/CD server (a hypervisor, storage appliance, backup product, database, network gear, or OT/industrial equipment) — route those to the appropriate other AIops-tools skill. Do NOT use for Kubernetes deploy state — use k8s-aiops. GitLab.com / Gitea Cloud SaaS accounts are out of scope: this tool targets self-managed instances.
  Preview — governed CI/CD operations with a built-in governance harness (audit, policy, token budget, undo, risk-tiers). Mock-validated only, not run against a live server; both GitLab CE and Gitea are free/self-hostable, so a home lab is the easiest live check.
installer:
  kind: uv
  package: cicd-aiops
argument-hint: "[a project path, pipeline/runner id, or describe your CI/CD task]"
allowed-tools:
  - Bash
metadata: {"openclaw":{"requires":{"env":["CICD_AIOPS_CONFIG"],"bins":["cicd-aiops"],"config":["~/.cicd-aiops/config.yaml","~/.cicd-aiops/secrets.enc"]},"optional":{"env":["CICD_AIOPS_MASTER_PASSWORD"]},"primaryEnv":"CICD_AIOPS_CONFIG","homepage":"https://github.com/AIops-tools/CICD-AIops","emoji":"🔁","os":["macos","linux"]}}
compatibility: >
  Standalone, self-governed CI/CD operations across self-managed GitLab (REST API v4 /api/v4/..., access token via PRIVATE-TOKEN header) and self-hosted Gitea (API v1 /api/v1/..., access token via "Authorization: token") — preview. Each target in the config names its own platform, and a name-keyed platform registry selects the API shape, so the same tools work on both and one config can span a mixed estate; surfaces one platform lacks (e.g. runner administration on Gitea) raise a teaching error listing what is available. The governance harness (audit, policy, token/runaway budget, undo, risk-tiers) is bundled in the package — no external skill-family dependency.
  All write operations are audited to a local SQLite DB under ~/.cicd-aiops/ (relocatable via CICD_AIOPS_HOME).
  Credentials: the GitLab personal/project access token or Gitea access token is stored ENCRYPTED in ~/.cicd-aiops/secrets.enc (Fernet/AES-128 + scrypt-derived key) — never plaintext on disk. Run 'cicd-aiops init' to onboard (it asks for the platform and base URL), or 'cicd-aiops secret set <target>' to add one. The store is unlocked by a master password from CICD_AIOPS_MASTER_PASSWORD (non-interactive/MCP/CI) or an interactive prompt (CLI on a TTY). A legacy plaintext env var CICD_<TARGET_NAME_UPPER>_SECRET is still honoured as a fallback with a deprecation warning (migrate with 'cicd-aiops secret migrate'). The token is presented as a PRIVATE-TOKEN header (GitLab) or an Authorization token header (Gitea) at request time and held only in memory; secrets are never logged or echoed.
  State-changing operations pass through the @governed_tool decorator (pre-check + budget guard + audit + risk-tier gate). delete_artifacts is risk=high with dry_run + an approver gate and is irreversible (priorState records the destroyed count/bytes). Reversible writes (pause_runner/resume_runner as an undo pair; update_branch_protection replaying prior settings) capture the real fetched before-state and record an inverse undo descriptor; retry_pipeline/cancel_pipeline record priorState (the pipeline's prior status) only.
  Webhooks: none — no outbound network calls beyond the configured GitLab / Gitea REST API.
  SSL: verify_ssl defaults to ON; the init wizard asks before disabling it for self-signed lab certs.
  Transitive dependencies: httpx (HTTP client) and the MCP SDK. No post-install scripts or background services.
  PREVIEW: mock-validated only — not run against a live server. Both GitLab CE and Gitea are free/self-hostable, so a home lab is the easiest live check.
---

# CICD AIops (preview)

> **Disclaimer**: Community-maintained open-source project, **not affiliated with, endorsed by, or sponsored by GitLab Inc. or the Gitea project.** GitLab and Gitea are trademarks of their respective owners. Source at [github.com/AIops-tools/CICD-AIops](https://github.com/AIops-tools/CICD-AIops) under the MIT license.

Governed CI/CD operations — **26 MCP tools** across **self-managed GitLab** (REST
`/api/v4/...`) and **self-hosted Gitea** (API `/api/v1/...`), every one wrapped with
the bundled `@governed_tool` harness: a local unified audit log under
`~/.cicd-aiops/`, policy engine, token/runaway budget guard, undo-token recording,
and graduated-autonomy risk tiers. A per-target `platform` field selects the API
shape, so the same tools work on both servers and one config can span a mixed
estate. The access token is stored **encrypted** (`~/.cicd-aiops/secrets.enc`,
Fernet + scrypt) — never plaintext on disk.

> **Standalone**: the governance harness is bundled in the package
> (`cicd_aiops.governance`) — no external skill-family dependency.
> **Preview / mock-only**: not run against a live server; both platforms are
> free/self-hostable, so a home lab is the easiest live check.

## What This Skill Does

| Group | Tools | Count | R/W |
|-------|-------|:-----:|:---:|
| **Server** | server_version, current_user, cicd_overview | 3 | read |
| **Projects** | list_projects, project_detail | 2 | read |
| **Pipelines** | list_pipelines, pipeline_detail, pipeline_jobs, job_trace_tail | 4 | read |
| **Runners** | list_runners, runner_detail | 2 | read |
| **Repo surface** | list_merge_requests, list_branches, list_protected_branches, list_releases | 4 | read |
| **Artifacts** | list_artifacts | 1 | read |
| **Flagship analyses** | pipeline_failure_rca, runner_health_rca, artifact_storage_bloat_analysis, stale_work_audit | 4 | read |
| **Writes** | retry_pipeline, cancel_pipeline, pause_runner, resume_runner, update_branch_protection | 5 | write (med) |
| **Writes** | delete_artifacts | 1 | write (**high**) |

The four flagship analyses are transparent heuristics that report their numbers,
never a black-box verdict: `pipeline_failure_rca` classifies each failed job from
its failure_reason + trace-tail markers (test-failure / dependency-network /
runner-timeout / oom / script-error) with matched evidence; `runner_health_rca`
flags offline/stale/paused runners, long-queued jobs, and per-tag saturation;
`artifact_storage_bloat_analysis` ranks projects by repo + artifact bytes and
estimates reclaimable bytes; `stale_work_audit` flags idle MRs/branches and
protection gaps.

## Quick Install

```bash
uv tool install cicd-aiops
cicd-aiops init       # wizard: pick platform (gitlab/gitea) + base URL + encrypted token
cicd-aiops doctor     # version endpoint + token-scope probe per target
```

## When to Use This Skill

- Get a one-shot snapshot (`overview` / `server_version` / `current_user`)
- Answer "why is CI red?" (`rca pipelines` / `pipeline_failure_rca`) → cause +
  action per failed pipeline, with the trace evidence that drove the call
- Find wedged capacity (`rca runners` / `runner_health_rca`) → offline/stale
  runners, long-queued jobs, saturated tags
- Reclaim disk (`rca storage` / `artifact_storage_bloat_analysis`) → ranked
  projects + reclaimable bytes, feeding `delete_artifacts --dry-run`
- Repo hygiene (`rca stale` / `stale_work_audit`) → idle MRs/branches,
  unprotected default branch, force-push gaps
- Safely act: `retry_pipeline` / `cancel_pipeline`, `pause_runner` /
  `resume_runner` (undo pair), `update_branch_protection` (undo replays prior
  settings), `delete_artifacts` (risk=high, dry-run + approver)

**Do NOT use when** the target is not a GitLab/Gitea CI/CD server — route
hypervisor, storage, backup, database, network, or OT/industrial work to the
appropriate other AIops-tools skill.

## Related Skills — Skill Routing

| If the user wants… | Use |
|--------------------|-----|
| Self-managed GitLab / Gitea CI/CD ops | **cicd-aiops** (this skill) |
| Kubernetes deploy state (what the cluster is actually running) | **k8s-aiops** |
| A non-CI/CD platform (hypervisor, storage, backup, database, network, OT edge) | the appropriate **other AIops-tools** skill |
| GitLab.com / Gitea Cloud SaaS accounts | out of scope for this tool |

## Common Workflows

### The pipeline is red

1. `pipelines list <project> --status failed` → recent failed pipelines
2. `rca pipelines <project>` → each failed job classified (test-failure /
   dependency-network / runner-timeout / oom / script-error) with evidence + action
3. Fix per the action, or `pipelines retry <project> <id> --dry-run` → re-run

### Jobs are stuck in the queue

1. `runners list` → offline/paused first
2. `rca runners` → stale contact ages, long-queued jobs, and which tag is
   saturated (queued jobs vs online runners)
3. `runners resume <id>` if a needed runner is paused (undo-recorded)

### The disk is filling up

1. `rca storage` → projects ranked by repo + artifact bytes, reclaimable estimate
2. `artifacts list <project>` → the actual files, sizes, expiry
3. `artifacts delete <project> --older-than-days 30 --dry-run` → preview, then
   re-run without `--dry-run` (risk=high; set `CICD_AUDIT_APPROVED_BY` +
   `CICD_AUDIT_RATIONALE`)

### Lock down the default branch (reversible)

1. `rca stale <project>` → protection gaps (unprotected default, force-push allowed)
2. `update_branch_protection` with `allow_force_push=False` — it captures the
   prior settings and records an undo that replays them

## Governance & Safety

- **Secure by default**: with no `~/.cicd-aiops/rules.yaml`, high/critical
  operations are denied unless `CICD_AUDIT_APPROVED_BY` names an approver (set
  `CICD_AUDIT_RATIONALE` too). `cicd-aiops init` seeds a starter rules.yaml; an
  operator-authored rules file is honoured as-is.
- Every tool is audited to `~/.cicd-aiops/audit.db` (relocatable via
  `CICD_AIOPS_HOME`).
- Writes support `--dry-run` and double confirmation at the CLI.
  `delete_artifacts` is irreversible (priorState records the destroyed
  count/bytes; audit only).
- Reversible writes capture the real fetched before-state and record an inverse
  descriptor (pause↔resume, protection→prior settings).

## References

- `references/capabilities.md` — full tool + platform + API-path reference
- `references/cli-reference.md` — CLI command reference
- `references/setup-guide.md` — onboarding, credentials, and connectivity

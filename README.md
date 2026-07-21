<!-- mcp-name: io.github.AIops-tools/cicd-aiops -->

# CICD AIops

**Governed AI-ops for self-managed GitLab and self-hosted Gitea.**

`cicd-aiops` is for the team running its *own* CI/CD forge — a GitLab instance
or a Gitea server on your hardware, in your lab, behind your VPN — who want an
AI agent that can answer "why did the pipeline fail?", "which runner is
wedged?", "where did 40 GB of artifact storage go?" and "what work went
stale?" and then act (retry, cancel, pause, delete, protect) **only** through
an audited, budgeted, risk-tiered, undo-recorded governance harness. It is not
a SaaS integration: it speaks the GitLab REST API v4 and the Gitea API v1
directly against your server, with credentials encrypted at rest.

> **Verification status**: modelled from each project's public API docs and
> exercised against mocked HTTP responses; there is no recorded end-to-end run
> against a live server yet. `cicd-aiops doctor` is the fastest live check —
> see [`docs/VERIFICATION.md`](docs/VERIFICATION.md).

> **Routing**: Do NOT use this for Kubernetes deploy state — use k8s-aiops.
> This tool ends at the CI/CD server's API (pipelines, runners, artifacts,
> repo hygiene).

## What this tool does, and does not, decide

It delivers CI/CD operations — reads and writes — accurately and efficiently, and
records every one of them. It does **not** decide whether a write is allowed to
happen. That is the agent's judgement, or the permission of the token you connect
it with: give it a GitLab/Gitea access token without write scope and the writes
fail at the server — the place that actually owns the permission.

So there is no read-only switch, no policy file, no approval gate to configure.
The one thing the tool guarantees is that nothing is silent: **every call, over
MCP and over the CLI alike, lands an audit row** in `~/.cicd-aiops/audit.db`,
and destructive writes still capture their before-state and record an inverse
where one exists.

> Each tool declares a `risk_level`, kept in agreement with its `[READ]`/`[WRITE]`
> documentation tag by a test, and carried into the audit row as a descriptive
> tier — so a reviewer can see at a glance that a row was a high-risk delete. It
> is a label, not a gate.

Running a smaller / local model? See
[agent-guardrails.md](skills/cicd-aiops/references/agent-guardrails.md) — it lists
the guardrails this tool enforces for you (so you don't spend prompt budget
restating them) and gives a ready-made system prompt for what's left.

## Quick start

```bash
uv tool install cicd-aiops        # or: pip install cicd-aiops

cicd-aiops init        # wizard: base URL + token (encrypted) + TLS verify
cicd-aiops doctor      # connectivity + token-scope probe per target
cicd-aiops overview    # version, identity, projects, runners at a glance
```

Then the interesting parts:

```bash
cicd-aiops rca pipelines dev/api        # classify recent failed pipelines
cicd-aiops rca runners                  # offline/stale runners, tag saturation
cicd-aiops rca storage                  # artifact/repo bloat, reclaimable bytes
cicd-aiops rca stale dev/api            # stale MRs/branches, protection gaps

cicd-aiops pipelines retry dev/api 42 --dry-run
cicd-aiops artifacts delete dev/api --older-than-days 30 --dry-run
```

Every write has `--dry-run` and a double confirmation, and executes through
the same governed path the MCP tools use — so CLI writes are audited too.

## Support scope

| Surface | GitLab (REST v4, self-managed) | Gitea (API v1, self-hosted) |
|---|---|---|
| Server version + token identity | ✅ | ✅ |
| Projects + storage statistics | ✅ (`statistics=true`) | ✅ (repo `size`) |
| Pipelines / runs, jobs, trace tails | ✅ | ✅ (Actions runs/jobs/logs) |
| Runner fleet (list/detail) | ✅ | ❌ teaching error (no API v1 equivalent) |
| Merge/pull requests, branches, protection, releases | ✅ | ✅ |
| Artifact inventory | ✅ (via jobs) | ✅ (Actions artifacts) |
| `retry_pipeline` / `cancel_pipeline` | ✅ | ❌ teaching error |
| `pause_runner` / `resume_runner` | ✅ | ❌ teaching error |
| `delete_artifacts` | ✅ | ❌ teaching error |
| `update_branch_protection` | ✅ | ✅ |

Where a platform lacks a surface, the platform registry raises a *teaching
error* naming the resources that **are** available — the agent learns instead
of hitting a mystery 404. GitLab.com / Gitea Cloud SaaS accounts are out of
scope by design: this tool targets self-managed instances.

## Flagship analyses (the reason this tool exists)

1. **`pipeline_failure_rca`** — pulls recent failed pipelines with failed-job
   trace tails and classifies each failure: *test-failure /
   dependency-network / runner-timeout / oom / script-error*, with the matched
   evidence, a cause, and an action per pipeline.
2. **`runner_health_rca`** — offline/stale/paused runners (contact-age
   threshold), jobs queued past a threshold, and per-tag saturation (queued
   jobs vs online runners).
3. **`artifact_storage_bloat_analysis`** — projects ranked by repo + artifact
   bytes, expired-but-kept artifacts, and a reclaimable-bytes estimate that
   feeds straight into `delete_artifacts --dry-run`.
4. **`stale_work_audit`** — merge/pull requests idle past N days, branches
   with no commits for N days, and protection gaps (unprotected default
   branch, force-push allowed).

All four are transparent heuristics: thresholds are named parameters and every
flag carries its numbers.

## Governance (built in, always on)

Every MCP tool and every CLI write runs through the vendored harness in
`cicd_aiops/governance/`. It records; it does not authorize (see above).

- **Audit** — every call (params, result, status, duration, risk tier, and any
  operator-supplied approver/rationale) is logged to `~/.cicd-aiops/audit.db`
  (relocatable via `CICD_AIOPS_HOME`). The CLI writes the same row the MCP path
  does — there is no unaudited entry point.
- **Runaway guard** — a safety backstop, not an authorization gate: the same
  call hammered in a tight loop trips a circuit breaker so a stuck agent can't
  burn unbounded calls/time. Disable with `CICD_RUNAWAY_MAX=0`; optional hard
  ceilings via `CICD_MAX_TOOL_CALLS` / `CICD_MAX_TOOL_SECONDS`.
- **Undo** — reversible writes record a replayable inverse in
  `~/.cicd-aiops/undo.db`, built from the *fetched* before-state:
  `pause_runner` ⇄ `resume_runner`, and `update_branch_protection` replays the
  prior settings. Irreversible writes (`retry_pipeline`, `cancel_pipeline`,
  `delete_artifacts`) record `priorState` (status / bytes+count) instead.
- **Risk tier** — a descriptive label on the audit row derived from
  `risk_level` (reads `low`; mutating writes `medium`; `delete_artifacts`
  `high`); it gates nothing.
- **Dry-run everywhere** — every write takes `dry_run=True` (MCP) /
  `--dry-run` (CLI) and previews without calling the server.
- **Sanitize** — all server-returned text is folded through an
  injection-safe normaliser (bounded strings, capped depth) before an agent
  sees it; all path parameters are percent-encoded so an identifier can never
  rewrite a URL.

### Secrets

Tokens live in `~/.cicd-aiops/secrets.enc` — Fernet-encrypted, key derived
from a master password via scrypt. Never plaintext on disk. Set
`CICD_AIOPS_MASTER_PASSWORD` for non-interactive/MCP use, and manage with
`cicd-aiops secret set|list|remove|migrate`. TLS verification defaults ON
(the init wizard asks before turning it off for lab certs).

## MCP server

26 governed tools (20 reads incl. the four flagship analyses, 6 writes).

```json
{
  "mcpServers": {
    "cicd-aiops": {
      "command": "uvx",
      "args": ["--from", "cicd-aiops", "cicd-aiops-mcp"],
      "env": {
        "CICD_AIOPS_MASTER_PASSWORD": "your-master-password"
      }
    }
  }
}
```

> **Env-block caveat**: MCP clients launch the server with a *minimal*
> environment — your shell profile is not sourced. Anything the server needs
> (`CICD_AIOPS_MASTER_PASSWORD`, `CICD_AIOPS_HOME`, and any optional
> `CICD_AUDIT_APPROVED_BY` audit annotation) must be set in the `env` block
> above, not in `~/.zshrc`.

Alternatively: `cicd-aiops mcp` (same server, CLI entry point).

## Configuration

`~/.cicd-aiops/config.yaml` (the wizard writes this):

```yaml
targets:
  - name: gl1
    platform: gitlab            # or: gitea
    base_url: https://git.example.com
    verify_ssl: true            # default ON; set false only for lab certs
```

The token for each target is stored encrypted under the target's name.
Relocate all state (config, audit, undo, secrets) with `CICD_AIOPS_HOME`.

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check .
```

## 缺功能？

缺功能提 issue/PR 欢迎留言 — if a GitLab/Gitea surface you need is missing
(runner administration on newer Gitea, per-job retry, scheduled pipelines,
group-level rollups…), open an issue or PR at
https://github.com/AIops-tools/CICD-AIops. The platform registry is designed
so a new resource is one path-map entry, not a refactor.

## License

MIT. GitLab is a trademark of GitLab Inc.; Gitea is a trademark of its
project owners. This project is independent and not affiliated with either.

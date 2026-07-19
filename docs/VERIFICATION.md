# Live verification — cicd-aiops

`cicd-aiops` is published and its behaviour is exercised by a **mock-only**
test suite. It has **not** yet been validated end-to-end against a live
self-managed GitLab or self-hosted Gitea server. Until it has, we make no claim
that the modelled REST paths and field shapes match a real deployment of either
platform.

This tool spans **two** platforms with deliberately **unequal** coverage behind
one tool surface, which shapes the verification obligation:

- A green run against GitLab says nothing about Gitea, and vice versa.
- Several surfaces exist only on GitLab (runner administration, pipeline
  retry/cancel). On a Gitea target these must raise a **teaching error** that
  names what *is* available — verifying that error is as important as verifying
  the happy path, because a silent failure there would be worse than no tool.

This document defines exactly what a live verification run must cover, and the
criteria for recording this tool as live-verified. It is deliberately
checklist-shaped so the result is reproducible and auditable — not a subjective
"seems fine".

## What the mock suite already guarantees

- Every module imports; the CLI builds; every MCP tool carries the
  `@governed_tool` harness marker (`tests/test_smoke.py`).
- The four analyses (`pipeline_failure_rca`, `runner_health_rca`,
  `artifact_storage_bloat_analysis`, `stale_work_audit`) are unit-tested against
  synthetic pipeline, job, trace, runner and project payloads — including the
  failure classification rules, the staleness thresholds and the rankings.
- The platform registry dispatches to the right API shape per target, and
  GitLab-only surfaces raise the teaching error on a Gitea target.
- Write tools carry the correct risk tier and record the correct inverse undo
  descriptor against a mocked connection: `pause_runner` ↔ `resume_runner`, and
  `update_branch_protection` → replay the captured prior settings.
- `delete_artifacts` is `high` risk and irreversible: priorState records the
  destroyed count and bytes, and **no** undo token is recorded.

What it does **not** guarantee: that the GitLab `/api/v4/...` paths, the Gitea
`/api/v1/...` paths, the job `failure_reason` values, the trace format, and the
storage-statistics fields exist as modelled on any real build of either server.

## Prerequisites for a live run

**Live verification is cheap here** — both platforms are free and
self-hostable from a container, so this is a realistic community self-test.

```bash
# GitLab CE
docker run -d --name gitlab-verify -p 8929:8929 \
  --shm-size 256m gitlab/gitlab-ce:latest

# Gitea
docker run -d --name gitea-verify -p 3000:3000 gitea/gitea:latest
```

Then, per platform:

- A **throwaway project/repository** with CI configured, which you are willing
  to run, break, fill with artifacts, and delete from. Never verify against a
  project real work depends on.
- An **access token** with least privilege (GitLab: `PRIVATE-TOKEN`; Gitea:
  `Authorization: token`).
- GitLab only: at least one **registered runner**, so runner administration and
  the runner-health RCA can be exercised at all.
- Deliberately produced material: **at least one genuinely failed pipeline**
  (ideally one per failure class), some **artifacts older than your age
  threshold**, and a **stale branch and open MR**. The analyses cannot be
  verified against a lab that happens to be clean.

```bash
uv tool install cicd-aiops
cicd-aiops init      # base URL + token (encrypted) + TLS verify
cicd-aiops doctor
```

Record the server versions — the modelled paths are the main risk, so a result
without versions is not a usable result.

## Verification checklist

Run the checklist **once per platform**. Tick every box. A box that cannot be
ticked is a verification gap — record it, do not silently pass.

Platform under test: ☐ GitLab ☐ Gitea — version: ____________

### 1. Connectivity (the fastest live gate)
- [ ] `cicd-aiops doctor` → all green: config, encrypted secret store, server
      reachable, and the token-scope probe passes for this target.
- [ ] `cicd-aiops overview` → server version, token identity, projects and
      (GitLab) runners match the web UI.

### 2. Reads return real, well-shaped data
- [ ] `cicd-aiops projects --limit 50` → real projects with **storage numbers**
      populated (GitLab needs `statistics=true`; Gitea reports repo `size`).
- [ ] `cicd-aiops pipelines list <project> --status failed -n 20` → the real
      failed pipelines, matching the UI.
- [ ] `cicd-aiops pipelines show <project> <pipeline-id>` and
      `pipelines jobs <project> <pipeline-id>` → correct stages, jobs and
      statuses.
- [ ] `cicd-aiops pipelines trace <project> <job-id> -n 120` → the real log
      tail (the trace format is a prime drift point, and the failure RCA reads
      it).
- [ ] `cicd-aiops artifacts list <project>` → real artifacts with sizes and
      expiry.
- [ ] GitLab only: `cicd-aiops runners list` and `runners show <runner-id>` →
      real runners with tags, status and last-contact times.
- [ ] MCP `list_branches`, `list_protected_branches`, `list_merge_requests`,
      `list_releases` → match the web UI for the project.

### 3. The four analyses judge correctly against reality
- [ ] `cicd-aiops rca pipelines <project>` → a deliberately failing test is
      classified **test-failure**; a job killed by memory limits is classified
      **oom**; a job that timed out is **runner-timeout**. Each classification
      cites evidence you can find in the trace.
- [ ] GitLab only: `cicd-aiops rca runners` → a runner you stopped shows a
      stale contact age; a tag with queued jobs and no online runner is
      reported as saturated; a healthy fleet produces no findings.
- [ ] `cicd-aiops rca storage --old-days 30` → the reclaimable estimate matches
      a manual sum of artifacts older than 30 days for that project.
- [ ] `cicd-aiops rca stale <project> --mr-days 14 --branch-days 60` → a branch
      and an MR you deliberately left idle are flagged with correct ages; fresh
      ones are not (no false positive). An unprotected default branch is
      reported as a protection gap.

### 4. A reversible write + its undo (governance closes the loop)
- [ ] GitLab only: `cicd-aiops runners pause <runner-id> --dry-run` → prints
      the call, changes nothing.
- [ ] GitLab only: `cicd-aiops runners pause <runner-id>` → the runner is
      genuinely paused in the UI; the result carries an `_undo_id`; a row lands
      in `~/.cicd-aiops/audit.db`.
- [ ] `cicd-aiops undo apply <id>` → the runner resumes (the recorded inverse
      runs).
- [ ] MCP `update_branch_protection` (e.g. `allow_force_push=False`) then
      `undo apply` → the **exact prior protection settings** are restored, not
      a default (proves undo captured the fetched before-state).
- [ ] GitLab only: `cicd-aiops pipelines retry <project> <pipeline-id>` → a new
      run actually starts and is audited.
- [ ] `cicd-aiops pipelines cancel <project> <running-pipeline-id>` → the run
      genuinely stops.

### 5. Platform asymmetry is honest
- [ ] On a **Gitea** target, `cicd-aiops runners list`,
      `cicd-aiops pipelines retry` and `cicd-aiops pipelines cancel` raise the
      **teaching error** naming what is available — they do not fail silently,
      return empty data, or pretend to succeed.
- [ ] On a Gitea target, everything the support matrix claims **is** supported
      (Actions runs/jobs/logs/artifacts, branches, protection, PRs, releases)
      genuinely works.

### 6. Governance actually gates
- [ ] With no `~/.cicd-aiops/rules.yaml`, the `high`-risk op
      (`cicd-aiops artifacts delete`) is **refused** unless
      `CICD_AUDIT_APPROVED_BY` is set — secure-by-default.
- [ ] With the approver set, `cicd-aiops artifacts delete <project>
      --older-than-days 30 --dry-run` reports the correct scope and deletes
      nothing.
- [ ] The confirmed run deletes exactly the artifacts in scope — no newer ones
      — is audited with the approver, rationale and destroyed count/bytes, and
      records **no** undo token.
- [ ] A tight poll loop trips the runaway budget guard rather than hammering
      the server.
- [ ] A failed operation is audited with `status=error` and records no undo.

### 7. Cleanup
- [ ] Resume any paused runner; restore the original branch protection.
- [ ] Delete the throwaway project.
- [ ] Remove the throwaway token from the secret store
      (`cicd-aiops secret rm <name>`) and revoke it on the server.
- [ ] Tear down the container.

## Criteria to consider it live-verified

Record this tool as live-verified **only when all of the following hold**:

1. The checklist is ticked against **both** platforms, with each version
   recorded (e.g. "verified on GitLab CE 17.x and Gitea 1.2x"). A single
   platform passing means only that platform is verified — say so explicitly
   rather than claiming the tool is verified.
2. Section 3 is ticked against **deliberately induced** failures, stale work
   and artifact bloat — not whatever the lab happened to contain.
3. Section 5 is ticked. A teaching error that does not fire is a correctness
   bug, not a documentation gap.
4. The irreversible-delete boxes in section 6 are verified by checking what
   survived, not by trusting the reported count.
5. Every REST path, `failure_reason` value or field-shape mismatch found during
   the run is fixed and covered by a regression test, with the server version
   where it differs noted.
6. The run is written up in this repo's release notes with the date and
   version, matching how the line records its other live-verified tools.

Until then this document stands as the accurate statement of status.

## Notes for maintainers

- `cicd-aiops doctor` is the single fastest live entry point; start there.
- Expect the first failures around **storage statistics** and the **job trace
  format** — both are optional/variable on real servers, and both feed an
  analysis that will silently under-report rather than crash if the shape is
  wrong.
- The two platforms drift independently. When a path is fixed for one, check
  whether the registry entry for the other needs the same fix.
- The verification story for the whole product line is tracked centrally; add
  this tool's result there once green so the verification-debt ledger stays
  accurate.

# Security Policy

Community-maintained open-source project, **not affiliated with, endorsed by, or
sponsored by GitLab Inc. or the Gitea project.**
Product and trademark names (GitLab, Gitea) belong to their owners.

## Reporting a vulnerability

Open a private security advisory on GitHub
(https://github.com/AIops-tools/CICD-AIops/security/advisories) or email
zhouwei008@gmail.com. Please do not open public issues for exploitable bugs.

## Credential handling

- Per-target secrets — the GitLab personal/project access token or the Gitea
  access token — are stored **encrypted** in `~/.cicd-aiops/secrets.enc`
  (Fernet/AES-128-CBC+HMAC, key derived from a master password via scrypt),
  file mode 600. Never plaintext on disk.
- The token is presented as a `PRIVATE-TOKEN` header (GitLab) or an
  `Authorization: token` header (Gitea) at request time and held only in
  memory; secrets are never logged, echoed, or included in tool output.
- A legacy plaintext env var (`CICD_<TARGET>_SECRET`) is honoured as a
  fallback with a deprecation warning — migrate with
  `cicd-aiops secret migrate`.
- TLS verification defaults ON; disabling it is an explicit per-target,
  wizard-confirmed choice intended for lab certs only.

## Blast-radius controls

- Every MCP tool and every CLI write runs through the `@governed_tool`
  harness: audit log (`~/.cicd-aiops/audit.db`), call/time budgets, a runaway
  breaker, graduated risk tiers, and undo-token recording.
- Secure by default: with no `rules.yaml`, high-risk writes
  (`delete_artifacts`) are denied unless `CICD_AUDIT_APPROVED_BY` names a
  human approver.
- Every write supports `dry_run`; the CLI double-confirms destructive
  operations.

## Input/output hardening

- All server-returned text (job traces, MR titles, branch names, runner
  descriptions) is folded through an injection-safe normaliser — bounded
  string length, capped nesting depth — before an agent sees it.
- All URL path parameters are percent-encoded; Gitea's `owner/repo` values
  are validated per segment (empty/`.`/`..` rejected) so an agent-supplied
  identifier can never rewrite a request path.

No webhooks, no telemetry, no outbound calls beyond the configured GitLab /
Gitea REST API.

# cicd-aiops — setup guide

## 1. Install

```bash
uv tool install cicd-aiops        # or: pip install cicd-aiops
```

Requires Python >= 3.11.

## 2. Create a token on the server

**GitLab (self-managed)** — Preferences → Access Tokens → new personal (or
project) access token with the `api` scope. Runner administration
(`pause_runner`/`resume_runner`, `/runners/all`) additionally needs an
admin-capable account.

**Gitea (self-hosted)** — Settings → Applications → Generate new token. Grant
read scopes for repository/issue and write where you want
`update_branch_protection` to work.

Least privilege applies: a read-only token still powers every read and all
four RCAs; only the six write tools need write scopes.

## 3. Onboard

```bash
cicd-aiops init
```

The wizard asks for:

1. **Master password** — encrypts `~/.cicd-aiops/secrets.enc` (Fernet +
   scrypt). For MCP / non-interactive use export
   `CICD_AIOPS_MASTER_PASSWORD=...`.
2. **Target name** (e.g. `gl1`), **platform** (`gitlab` / `gitea`), and
   **base URL** (e.g. `https://git.example.com` — scheme optional, added
   automatically).
3. **TLS verification** — defaults to **Yes**; answer No only for
   self-signed lab certs.
4. **Access token** — prompted hidden, stored encrypted, never in
   config.yaml.

It also seeds `~/.cicd-aiops/rules.yaml` with the dual-control tier
(high-risk writes need a named approver) unless one already exists.

Resulting `~/.cicd-aiops/config.yaml`:

```yaml
targets:
  - name: gl1
    platform: gitlab
    base_url: https://git.example.com
    verify_ssl: true
  - name: gt1
    platform: gitea
    base_url: https://gitea.example.com
    verify_ssl: true
```

## 4. Verify

```bash
cicd-aiops doctor
```

Checks per target: config present, encrypted store + token present, the
server's **version endpoint** answers, and a **token-scope probe**
(`current_user`) confirms the token authenticates. A reachable server with a
dud token is reported as unhealthy.

## 5. MCP client config

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

MCP clients do not source your shell profile — set
`CICD_AIOPS_MASTER_PASSWORD` (and `CICD_AUDIT_APPROVED_BY` if the agent may
run high-risk writes) in the `env` block.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `401/403` in doctor | token expired or missing `api` scope — reissue and `cicd-aiops secret set <target>` |
| `Could not reach ...` | check `base_url`, VPN/network path, and that the API is enabled |
| self-signed cert errors | re-run `init` and answer No to TLS verify (lab only) |
| `Resource ... not available on platform 'gitea'` | expected: runner admin / pipeline retry / artifact delete are GitLab surfaces in v0.1 |
| high-risk write denied | set `CICD_AUDIT_APPROVED_BY` + `CICD_AUDIT_RATIONALE`, or edit `rules.yaml` |

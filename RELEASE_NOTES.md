# Release notes — cicd-aiops 0.2.1

Previous release: 0.2.0.

## Fixed: unsupported resources were reported as a missing config key

Asking Gitea for a GitLab-only resource produced:

    Error: Missing required key or environment variable: "Resource 'runners' is
    not available on platform 'gitea'. Available resources: ..."

The correct explanation was inside the quotes, but the headline sent the reader
hunting a config/env problem that does not exist. The cause: "this platform has no
such resource" was signalled with a bare `KeyError`, and the CLI assumed every
`KeyError` meant a missing config key.

Unsupported resources now raise a dedicated `UnsupportedResource` — a `KeyError`
subclass, so any existing `except KeyError` keeps working — and the CLI reports it
as what it is. `proxy-aiops` already had this pattern (`UnsupportedOperation`); this
repo had diverged from it.

## Live-verified

Against **Gitea 1.27.0**: `doctor` including the token-scope probe, reads
cross-checked against Gitea's API, and `rca pipelines/stale/storage`. See
[docs/VERIFICATION.md](docs/VERIFICATION.md) — **GitLab remains unverified** and is
the richer branch (runners, job traces, artifact retention).

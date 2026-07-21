# Release notes — cicd-aiops 0.5.0

Previous release: 0.4.0.

## Live-verified against real GitLab CE 19.2

cicd's GitLab branch was pointed at a real current GitLab for the first time. Reads, the flagship RCA, a governed write (audited, real effect, undo reverted on the server), and the CLI audit path all checked out — and it surfaced the two `list_projects` field bugs fixed below.


### In this tool

- **Fixes two field bugs found live against real GitLab CE 19.2.** `list_projects` now surfaces each project's `name` (it only mapped the path before), and reports byte counts (`repoBytes` / `artifactsBytes` / `storageBytes`) as **integers** — GitLab's `repository_size` was being rendered as a float (`3870.0` bytes).

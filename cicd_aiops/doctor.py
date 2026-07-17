"""Environment and connectivity diagnostics for CICD AIops."""

from __future__ import annotations

from rich.console import Console

from cicd_aiops.config import CONFIG_FILE, ENV_FILE, load_config
from cicd_aiops.secretstore import SECRETS_FILE, check_permissions, has_store

_console = Console()


def run_doctor(skip_auth: bool = False) -> int:
    """Check config, secrets, and (optionally) connectivity + token scope.

    Returns a process exit code: 0 healthy, 1 problems found. Connectivity
    failures are reported as status, never raised as tracebacks (a doctor must
    survive the thing it diagnoses being unhealthy).
    """
    problems = 0

    if not CONFIG_FILE.exists():
        _console.print(f"[red]✗ Config file missing: {CONFIG_FILE}[/]")
        _console.print("[yellow]  Run 'cicd-aiops init' to set up your first target.[/]")
        return 1
    _console.print(f"[green]✓ Config file present: {CONFIG_FILE}[/]")

    try:
        config = load_config()
    except Exception as exc:  # noqa: BLE001 — report, do not crash
        _console.print(f"[red]✗ Config load failed: {exc}[/]")
        return 1

    if not config.targets:
        _console.print("[red]✗ No targets configured[/]")
        return 1
    _console.print(f"[green]✓ {len(config.targets)} target(s) configured[/]")

    if has_store():
        _console.print(f"[green]✓ Encrypted secret store present: {SECRETS_FILE}[/]")
        perm_warning = check_permissions()
        if perm_warning:
            _console.print(f"[yellow]! {perm_warning}[/]")
    elif ENV_FILE.exists():
        _console.print(
            f"[yellow]! Using legacy plaintext .env ({ENV_FILE}). Migrate with "
            f"'cicd-aiops secret migrate'.[/]"
        )
    else:
        _console.print(
            "[yellow]! No secret store yet. Run 'cicd-aiops init' to set up "
            "credentials (stored encrypted).[/]"
        )
        problems += 1

    for target in config.targets:
        try:
            _ = target.secret
            _console.print(
                f"[green]✓ Token present for '{target.name}' ({target.platform})[/]"
            )
        except OSError as exc:
            _console.print(f"[red]✗ {exc}[/]")
            problems += 1

    if skip_auth:
        _console.print("[dim]Skipping connectivity check (--skip-auth).[/]")
        return 1 if problems else 0

    from cicd_aiops.connection import ConnectionManager

    mgr = ConnectionManager(config)
    for target in config.targets:
        try:
            conn = mgr.connect(target.name)
            # Cheap reads that exist on both platforms: server version, then
            # a token-scope probe (who am I?).
            version = conn.get(conn.platform.path("version"))
            ver = version.get("version") if isinstance(version, dict) else version
            _console.print(
                f"[green]✓ Connected to '{target.name}' ({target.platform} "
                f"{target.base_url}) — server version {ver}[/]"
            )
        except Exception as exc:  # noqa: BLE001 — connectivity is a status, not a crash
            _console.print(f"[red]✗ Connect to '{target.name}' failed: {exc}[/]")
            problems += 1
            continue
        try:
            user = conn.get(conn.platform.path("current_user"))
            login = (
                user.get("username") or user.get("login") or "(unknown)"
                if isinstance(user, dict)
                else "(unknown)"
            )
            _console.print(
                f"[green]✓ Token scope probe OK for '{target.name}' — "
                f"authenticated as '{login}'[/]"
            )
        except Exception as exc:  # noqa: BLE001 — token scope is a status, not a crash
            _console.print(
                f"[red]✗ Token scope probe failed for '{target.name}': {exc}[/]"
            )
            problems += 1

    return 1 if problems else 0

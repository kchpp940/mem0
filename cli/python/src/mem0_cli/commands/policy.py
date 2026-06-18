"""Lifecycle policy commands (``mem0 policy show`` / ``mem0 policy set``)."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table

from mem0_cli.backend.base import Backend
from mem0_cli.formatting import format_agent_envelope, format_json, print_error, print_success

console = Console()
err_console = Console(stderr=True)


VALID_SCOPES = {"default", "workspace", "user", "agent", "category"}
ENTITY_SCOPES = {"user", "agent", "category"}


def _policy_ttl_text(policy: Any) -> str:
    if not isinstance(policy, dict):
        return "--"
    days = policy.get("default_ttl_days")
    enabled = policy.get("enabled", True)
    if not enabled:
        return "[dim]disabled[/dim]"
    if days is None:
        return "[blue]permanent[/blue]"
    try:
        days = int(days)
    except (TypeError, ValueError):
        return str(days)
    if days == 1:
        return "1 day"
    return f"{days} days"


def _scope_display(scope: str, scope_id: str | None) -> str:
    if scope in ENTITY_SCOPES and scope_id:
        return f"{scope} [cyan]{scope_id}[/cyan]"
    return scope


def cmd_policy_show(backend: Backend, *, output: str = "table") -> None:
    """Display the full lifecycle policy hierarchy."""
    from mem0_cli.state import is_agent_mode, set_current_command

    set_current_command("policy show")
    if is_agent_mode():
        output = "agent"

    try:
        data = backend.get_lifecycle_policies()
    except Exception as e:
        print_error(err_console, str(e))
        import typer
        raise typer.Exit(1) from None

    if output == "agent":
        format_agent_envelope(console, command="policy_show", data=data, duration_ms=0)
        return
    if output == "json":
        format_json(console, data)
        return
    if output == "quiet":
        return

    default = data.get("default") or {}
    workspace = data.get("workspace")
    users = data.get("users") or {}
    agents = data.get("agents") or {}
    categories = data.get("categories") or {}

    table = Table(
        title="Lifecycle Retention Policies",
        header_style="bold",
        show_lines=False,
        padding=(0, 1),
    )
    table.add_column("Scope", style="bold")
    table.add_column("Retention", justify="right")
    table.add_column("Source")

    table.add_row("default", _policy_ttl_text(default), "default scope")
    if workspace:
        table.add_row("workspace", _policy_ttl_text(workspace), "workspace scope")
    else:
        table.add_row("workspace", "[dim]--[/dim]", "[dim](not configured)[/dim]")

    if users:
        for uid, pol in users.items():
            table.add_row(f"user [cyan]{uid}[/cyan]", _policy_ttl_text(pol), f"users.{uid}")
    else:
        table.add_row("users", "[dim]--[/dim]", "[dim](no per-user policies)[/dim]")

    if agents:
        for aid, pol in agents.items():
            table.add_row(f"agent [cyan]{aid}[/cyan]", _policy_ttl_text(pol), f"agents.{aid}")
    else:
        table.add_row("agents", "[dim]--[/dim]", "[dim](no per-agent policies)[/dim]")

    if categories:
        for name, pol in categories.items():
            table.add_row(f"category [cyan]{name}[/cyan]", _policy_ttl_text(pol), f"categories.{name}")
    else:
        table.add_row("categories", "[dim]--[/dim]", "[dim](no per-category policies)[/dim]")

    console.print()
    console.print(
        "[dim]Precedence: request → category → user → agent → workspace → default → permanent[/dim]"
    )
    console.print(table)


def cmd_policy_set(
    backend: Backend,
    *,
    scope: str,
    scope_id: str | None,
    default_ttl_days: int | None,
    enabled: bool | None,
    remove: bool,
    permanent: bool,
    ttl_was_provided: bool,
    output: str,
) -> None:
    """Upsert or remove a lifecycle policy at a specific scope."""
    from mem0_cli.state import is_agent_mode, set_current_command

    set_current_command("policy set")
    if is_agent_mode():
        output = "agent"

    # For per-entity scopes, removing is a separate path
    if remove:
        if scope not in ENTITY_SCOPES:
            print_error(
                err_console,
                "--remove is only valid for scopes: user, agent, category.",
            )
            import typer
            raise typer.Exit(1)
        if not scope_id:
            print_error(err_console, "--remove requires a scope_id (entity ID).")
            import typer
            raise typer.Exit(1)

    effective_days: int | None = default_ttl_days
    if ttl_was_provided and permanent:
        effective_days = None

    try:
        result = backend.set_lifecycle_policy(
            scope=scope,
            scope_id=scope_id,
            default_ttl_days=effective_days if (ttl_was_provided and not remove) else None,
            enabled=enabled,
            remove=remove,
        )
    except Exception as e:
        print_error(err_console, str(e))
        import typer
        raise typer.Exit(1) from None

    if output == "agent":
        format_agent_envelope(console, command="policy_set", data=result, duration_ms=0)
        return
    if output == "json":
        format_json(console, result)
        return
    if output == "quiet":
        return

    if remove:
        print_success(console, f"Removed policy for {_scope_display(scope, scope_id)}.")
    else:
        desc = f"scope={_scope_display(scope, scope_id)}"
        changes: list[str] = []
        if ttl_was_provided:
            changes.append(
                "retention=permanent" if effective_days is None else f"retention={effective_days}d"
            )
        if enabled is not None:
            changes.append(f"enabled={'yes' if enabled else 'no'}")
        change_str = ", ".join(changes) if changes else "(no policy fields changed - call with --ttl-days, --permanent, or --enabled/--disabled)"
        print_success(console, f"Updated policy: {desc} · {change_str}")

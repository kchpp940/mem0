"""Utility commands: status, version, import."""

from __future__ import annotations

import json
import time as _time
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import track

from mem0_cli import __version__
from mem0_cli.backend.base import Backend
from mem0_cli.branding import (
    BRAND_COLOR,
    DIM_COLOR,
    ERROR_COLOR,
    SUCCESS_COLOR,
    print_error,
    print_success,
    timed_status,
)
from mem0_cli.option_builder import build_scope
from mem0_cli.output import OutputRenderer

console = Console()
err_console = Console(stderr=True)


def _resolve_output(output: str) -> str:
    from mem0_cli.state import is_agent_mode

    if is_agent_mode():
        return "agent"
    return output


def cmd_status(
    backend: Backend,
    *,
    user_id: str | None = None,
    agent_id: str | None = None,
    output: str = "text",
) -> None:
    """Check connectivity and auth."""
    from mem0_cli.state import set_current_command

    set_current_command("status")
    output = _resolve_output(output)
    renderer = OutputRenderer(console, output_format=output, command="status", err_console=err_console)

    _start = _time.perf_counter()
    with timed_status(err_console, "Checking connection...") as _ts:
        result = backend.status(user_id=user_id, agent_id=agent_id)
    _elapsed = _time.perf_counter() - _start

    renderer.set_duration(seconds=_elapsed)

    if output in ("json", "agent"):
        renderer.data({
            "connected": result.get("connected", False),
            "backend": result.get("backend", "?"),
            "base_url": result.get("base_url", ""),
        })
        return

    lines = []
    if result.get("connected"):
        lines.append(f"  [{SUCCESS_COLOR}]●[/] Connected")
    else:
        lines.append(f"  [{ERROR_COLOR}]●[/] Disconnected")

    lines.append(f"  [{DIM_COLOR}]Backend:[/]  {result.get('backend', '?')}")
    if result.get("base_url"):
        lines.append(f"  [{DIM_COLOR}]API URL:[/]  {result['base_url']}")
    if result.get("error"):
        lines.append(f"  [{ERROR_COLOR}]Error:[/]    {result['error']}")
        if "Authentication failed" in str(result["error"]):
            lines.append("")
            lines.append(
                f"  [{DIM_COLOR}]Run [bold]mem0 init[/bold] to reconfigure your API key[/]"
            )
            lines.append(
                f"  [{DIM_COLOR}]Get a key at [bold]https://app.mem0.ai/dashboard/api-keys?utm_source=oss&utm_medium=cli-python[/bold][/]"
            )
    lines.append(f"  [{DIM_COLOR}]Latency:[/]  {_elapsed:.2f}s")

    content = "\n".join(lines)
    panel = Panel(
        content,
        title=f"[{BRAND_COLOR}]Connection Status[/]",
        title_align="left",
        border_style=BRAND_COLOR,
        padding=(1, 1),
    )
    console.print()
    console.print(panel)
    console.print()


def cmd_version() -> None:
    """Show version."""
    console.print(f"  [{BRAND_COLOR}]◆ Mem0[/] CLI v{__version__}")


def cmd_import(
    backend: Backend,
    file_path: str,
    *,
    user_id: str | None,
    agent_id: str | None,
    output: str = "text",
) -> None:
    """Import memories from a JSON file."""
    from mem0_cli.state import set_current_command

    set_current_command("import")
    output = _resolve_output(output)
    scope = build_scope(user_id=user_id, agent_id=agent_id)
    renderer = OutputRenderer(console, output_format=output, command="import", scope=scope, err_console=err_console)

    try:
        data = json.loads(Path(file_path).read_text())
    except (FileNotFoundError, json.JSONDecodeError) as e:
        renderer.error(f"Failed to read file: {e}", error_code="file_error")
        raise typer.Exit(1) from None

    if not isinstance(data, list):
        data = [data]

    added = 0
    failed = 0
    _start = _time.perf_counter()
    for item in track(
        data, description=f"[{DIM_COLOR}]Importing memories...[/]", console=err_console
    ):
        content = item.get("memory", item.get("text", item.get("content", "")))
        if not content:
            failed += 1
            continue
        try:
            backend.add(
                content=content,
                user_id=user_id or item.get("user_id"),
                agent_id=agent_id or item.get("agent_id"),
                metadata=item.get("metadata"),
            )
            added += 1
        except Exception:
            failed += 1
    _elapsed = _time.perf_counter() - _start

    renderer.set_duration(seconds=_elapsed)

    if output in ("json", "agent"):
        renderer.data({"added": added, "failed": failed})
        return

    print_success(err_console, f"Imported {added} memories ({_elapsed:.2f}s)")
    if failed:
        print_error(err_console, f"{failed} memories failed to import.")

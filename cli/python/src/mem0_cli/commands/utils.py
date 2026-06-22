"""Utility commands: status, version, import (layered architecture)."""

from __future__ import annotations

from rich.console import Console
from rich.progress import track

from mem0_cli import __version__
from mem0_cli.branding import BRAND_COLOR, DIM_COLOR
from mem0_cli.core import renderers
from mem0_cli.core.console import err_console as _wrapper_err_console
from mem0_cli.core.requests import iter_import_items
from mem0_cli.core.wrapper import (
    CommandContext,
    build_command_context,
    execute,
)

# ── Backwards-compatible module-level consoles.  Legacy code and tests patch
# these names; rendering actually flows through wrapper/renderers consoles now.
console = Console()
err_console = Console(stderr=True)


def cmd_version() -> None:
    Console().print(f"  [{BRAND_COLOR}]◆ Mem0[/] CLI v{__version__}")


def cmd_status(
    backend,
    *,
    config=None,
    user_id: str | None = None,
    agent_id: str | None = None,
    output: str = "text",
) -> None:
    ctx = build_command_context(
        command_name="status",
        backend=backend,
        config=config,
        output=output,
    )

    def action(_ctx: CommandContext):
        result = _ctx.backend.status(user_id=user_id, agent_id=agent_id)
        renderers.render_status(_ctx.render_ctx, result)

    execute(ctx, action, spinner="Checking connection...")


def cmd_import(
    backend,
    file_path: str,
    *,
    config=None,
    user_id: str | None = None,
    agent_id: str | None = None,
    output: str = "text",
) -> None:
    ctx = build_command_context(
        command_name="import",
        backend=backend,
        config=config,
        output=output,
        user_id=user_id,
        agent_id=agent_id,
    )

    def action(_ctx: CommandContext):
        items, _total = iter_import_items(
            file_path,
            user_id=user_id,
            agent_id=agent_id,
        )
        added = 0
        failed = _total - len(items)  # items without content already counted
        for payload in track(
            items,
            description=f"[{DIM_COLOR}]Importing memories...[/]",
            console=_wrapper_err_console,
        ):
            try:
                _ctx.backend.add(**payload)
                added += 1
            except Exception:
                failed += 1
        renderers.render_import(_ctx.render_ctx, added, failed)

    execute(ctx, action)

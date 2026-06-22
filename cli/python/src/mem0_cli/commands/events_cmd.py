"""Background event inspection commands (layered architecture)."""

from __future__ import annotations

from mem0_cli.core import renderers
from mem0_cli.core.options import require_positive
from mem0_cli.core.wrapper import (
    CommandContext,
    build_command_context,
    execute,
)


def cmd_event_list(
    backend,
    *,
    config=None,
    page: int = 1,
    page_size: int = 20,
    output: str = "table",
) -> None:
    require_positive(page, field="--page")
    require_positive(page_size, field="--page-size")

    ctx = build_command_context(
        command_name="event list",
        backend=backend,
        config=config,
        output=output,
    )

    def action(_ctx: CommandContext):
        results = _ctx.backend.list_events(page=page, page_size=page_size)
        renderers.render_event_list(_ctx.render_ctx, results)

    execute(ctx, action, spinner="Listing events...")


def cmd_event_status(
    backend,
    event_id: str,
    *,
    config=None,
    output: str = "text",
) -> None:
    ctx = build_command_context(
        command_name="event status",
        backend=backend,
        config=config,
        output=output,
    )

    def action(_ctx: CommandContext):
        result = _ctx.backend.get_event(event_id)
        renderers.render_event_status(_ctx.render_ctx, result)

    execute(ctx, action, spinner="Fetching event status...")

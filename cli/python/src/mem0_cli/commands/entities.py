"""Entity management commands (layered architecture)."""

from __future__ import annotations

from mem0_cli.core import renderers
from mem0_cli.core.errors import InputError
from mem0_cli.core.requests import build_entity_delete_payload
from mem0_cli.core.wrapper import (
    CommandContext,
    build_command_context,
    confirm_destructive,
    execute,
)

_VALID_ENTITY_TYPES = {"users", "agents", "apps", "runs"}


def cmd_entities_list(
    backend,
    entity_type: str,
    *,
    config=None,
    output: str = "table",
) -> None:
    ctx = build_command_context(
        command_name="entity list",
        backend=backend,
        config=config,
        output=output,
    )

    def action(_ctx: CommandContext):
        if entity_type not in _VALID_ENTITY_TYPES:
            raise InputError(
                f"Invalid entity type: {entity_type}. Use: {', '.join(sorted(_VALID_ENTITY_TYPES))}"
            )
        results = _ctx.backend.entities(entity_type)
        renderers.render_entity_list(_ctx.render_ctx, entity_type, results)

    execute(ctx, action, spinner=f"Fetching {entity_type}...")


def cmd_entities_delete(
    backend,
    *,
    config=None,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    output: str = "text",
) -> None:
    ctx = build_command_context(
        command_name="entity delete",
        backend=backend,
        config=config,
        output=output,
        user_id=user_id,
        agent_id=agent_id,
        app_id=app_id,
        run_id=run_id,
    )

    def action(_ctx: CommandContext):
        # Validate scope & build payload (raises InputError if no IDs)
        payload = build_entity_delete_payload(scope=_ctx.ids)

        if dry_run:
            # Bypass backend call; renderer handles text/json/quiet output
            renderers.render_entity_delete(_ctx.render_ctx, {}, dry_run=True)
            return

        label = _ctx.scope.scope_label()
        confirm_destructive(
            _ctx,
            f"Delete entity {label} AND all its memories?",
            force=force,
        )
        result = _ctx.backend.delete_entities(**payload)
        renderers.render_entity_delete(_ctx.render_ctx, result)

    execute(ctx, action, spinner="Deleting entity...")

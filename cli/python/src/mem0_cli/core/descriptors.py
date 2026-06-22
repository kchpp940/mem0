"""Command descriptor registrations.

Every CLI command is declared here as a :class:`CommandDescriptor`.  The
``commands/*.py`` modules import their descriptor and pass it to
:func:`~mem0_cli.core.registry.run_command`, eliminating the need to
hand-write the context → payload → backend → renderer loop in each
command function.
"""

from __future__ import annotations

from mem0_cli.core import renderers, requests
from mem0_cli.core.registry import CommandDescriptor, register

# ── Action overrides (must be defined before referencing in descriptors) ───


def _import_action(ctx, kwargs):  # type: ignore[no-untyped-def]
    from rich.progress import track

    from mem0_cli.branding import DIM_COLOR
    from mem0_cli.core.console import err_console as _err_console
    from mem0_cli.core.requests import iter_import_items

    file_path = kwargs["file_path"]
    user_id = kwargs.get("user_id")
    agent_id = kwargs.get("agent_id")
    items, _total = iter_import_items(file_path, user_id=user_id, agent_id=agent_id)
    added = 0
    failed = _total - len(items)
    for payload in track(
        items,
        description=f"[{DIM_COLOR}]Importing memories...[/]",
        console=_err_console,
    ):
        try:
            ctx.backend.add(**payload)
            added += 1
        except Exception:
            failed += 1
    renderers.render_import(ctx.render_ctx, added, failed)


def _config_data_for_display(config):  # type: ignore[no-untyped-def]
    from mem0_cli.config import redact_key

    return {
        "defaults": {
            "user_id": config.defaults.user_id or None,
            "agent_id": config.defaults.agent_id or None,
            "app_id": config.defaults.app_id or None,
            "run_id": config.defaults.run_id or None,
        },
        "platform": {
            "api_key": redact_key(config.platform.api_key),
            "base_url": config.platform.base_url,
        },
    }


def _config_show_action(ctx, kwargs):  # type: ignore[no-untyped-def]
    data = _config_data_for_display(ctx.config)
    renderers.render_config_show(ctx.render_ctx, data)


def _config_get_action(ctx, kwargs):  # type: ignore[no-untyped-def]
    from mem0_cli.config import get_nested_value, redact_key
    from mem0_cli.core.errors import InputError

    key = kwargs["key"]
    value = get_nested_value(ctx.config, key)
    if value is None:
        raise InputError(f"Unknown config key: {key}")
    display = redact_key(str(value)) if ("api_key" in key or "key" in key.split(".")[-1:]) else str(value)
    renderers.render_config_get(ctx.render_ctx, key, display)


def _config_set_action(ctx, kwargs):  # type: ignore[no-untyped-def]
    from mem0_cli.config import redact_key, save_config, set_nested_value
    from mem0_cli.core.errors import InputError

    key = kwargs["key"]
    value = kwargs["value"]
    if not set_nested_value(ctx.config, key, value):
        raise InputError(f"Unknown config key: {key}")
    save_config(ctx.config)
    display = redact_key(value) if "key" in key else value
    renderers.render_config_set(ctx.render_ctx, key, display)


def _entity_list_action(ctx, kwargs):  # type: ignore[no-untyped-def]
    from mem0_cli.core.errors import InputError

    entity_type = kwargs["entity_type"]
    valid = {"users", "agents", "apps", "runs"}
    if entity_type not in valid:
        raise InputError(f"Invalid entity type: {entity_type}. Use: {', '.join(sorted(valid))}")
    results = ctx.backend.entities(entity_type)
    renderers.render_entity_list(ctx.render_ctx, entity_type, results)


def _entity_delete_action(ctx, kwargs):  # type: ignore[no-untyped-def]
    from mem0_cli.core.wrapper import confirm_destructive

    dry_run = kwargs.get("dry_run", False)
    force = kwargs.get("force", False)
    scope = kwargs.get("scope", {})
    payload = requests.build_entity_delete_payload(scope=scope)

    if dry_run:
        renderers.render_entity_delete(ctx.render_ctx, {}, dry_run=True)
        return

    label = ctx.scope.scope_label()
    confirm_destructive(ctx, f"Delete entity {label} AND all its memories?", force=force)
    result = ctx.backend.delete_entities(**payload)
    renderers.render_entity_delete(ctx.render_ctx, result)


# ── Memory ────────────────────────────────────────────────────────────────

ADD = register(
    CommandDescriptor(
        name="add",
        backend_method="add",
        renderer=renderers.render_add_result,
        needs_scope=True,
        payload_builder=requests.build_add_payload,
        spinner="Adding memory...",
    )
)

SEARCH = register(
    CommandDescriptor(
        name="search",
        backend_method="search",
        renderer=renderers.render_search_results,
        needs_scope=True,
        payload_builder=requests.build_search_payload,
        spinner="Searching memories...",
    )
)

GET = register(
    CommandDescriptor(
        name="get",
        backend_method="get",
        renderer=renderers.render_single_memory,
        needs_scope=False,
        spinner="Fetching memory...",
    )
)

LIST = register(
    CommandDescriptor(
        name="list",
        backend_method="list_memories",
        renderer=renderers.render_list_memories,
        needs_scope=True,
        payload_builder=requests.build_list_payload,
        spinner="Listing memories...",
    )
)

UPDATE = register(
    CommandDescriptor(
        name="update",
        backend_method="update",
        renderer=renderers.render_update_result,
        needs_scope=False,
        payload_builder=requests.build_update_payload,
        spinner="Updating memory...",
    )
)

DELETE = register(
    CommandDescriptor(
        name="delete",
        backend_method="delete",
        renderer=renderers.render_delete_result,
        needs_scope=False,
        payload_builder=requests.build_delete_payload,
        spinner="Deleting memory...",
        dry_run_short_circuit=True,
    )
)

DELETE_ALL = register(
    CommandDescriptor(
        name="delete_all",
        backend_method="delete",
        renderer=renderers.render_delete_all_result,
        needs_scope=True,
        payload_builder=requests.build_delete_all_payload,
        spinner="Deleting all memories...",
        confirm_message="Delete ALL your memories?",
        dry_run_short_circuit=True,
    )
)

# ── Status / Import ───────────────────────────────────────────────────────

STATUS = register(
    CommandDescriptor(
        name="status",
        backend_method="status",
        renderer=renderers.render_status,
        needs_scope=False,
        spinner="Checking connection...",
    )
)

IMPORT = register(
    CommandDescriptor(
        name="import",
        backend_method="add",
        renderer=renderers.render_import,
        needs_scope=True,
        spinner=None,
        action_override=_import_action,
    )
)

# ── Config ────────────────────────────────────────────────────────────────

CONFIG_SHOW = register(
    CommandDescriptor(
        name="config show",
        backend_method=None,
        renderer=renderers.render_config_show,
        needs_scope=False,
        spinner=None,
        action_override=_config_show_action,
    )
)

CONFIG_GET = register(
    CommandDescriptor(
        name="config get",
        backend_method=None,
        renderer=renderers.render_config_get,
        needs_scope=False,
        spinner=None,
        action_override=_config_get_action,
    )
)

CONFIG_SET = register(
    CommandDescriptor(
        name="config set",
        backend_method=None,
        renderer=renderers.render_config_set,
        needs_scope=False,
        spinner=None,
        action_override=_config_set_action,
    )
)

# ── Entities ──────────────────────────────────────────────────────────────

ENTITY_LIST = register(
    CommandDescriptor(
        name="entity list",
        backend_method="entities",
        renderer=renderers.render_entity_list,
        needs_scope=False,
        spinner="Fetching entities...",
        action_override=_entity_list_action,
    )
)

ENTITY_DELETE = register(
    CommandDescriptor(
        name="entity delete",
        backend_method="delete_entities",
        renderer=renderers.render_entity_delete,
        needs_scope=True,
        payload_builder=requests.build_entity_delete_payload,
        spinner="Deleting entity...",
        confirm_message="Delete entity AND all its memories?",
        dry_run_short_circuit=True,
        action_override=_entity_delete_action,
    )
)

# ── Events ────────────────────────────────────────────────────────────────

EVENT_LIST = register(
    CommandDescriptor(
        name="event list",
        backend_method="list_events",
        renderer=renderers.render_event_list,
        needs_scope=False,
        spinner="Listing events...",
    )
)

EVENT_STATUS = register(
    CommandDescriptor(
        name="event status",
        backend_method="get_event",
        renderer=renderers.render_event_status,
        needs_scope=False,
        spinner="Fetching event status...",
    )
)

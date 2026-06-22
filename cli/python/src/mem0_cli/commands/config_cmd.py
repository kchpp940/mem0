"""Config management commands: show, set, get (layered architecture)."""

from __future__ import annotations

from rich.console import Console

from mem0_cli.config import (
    get_nested_value,
    load_config,
    redact_key,
    save_config,
    set_nested_value,
)
from mem0_cli.core import renderers
from mem0_cli.core.errors import InputError
from mem0_cli.core.wrapper import (
    CommandContext,
    build_command_context,
    execute,
)

# ── Backwards-compatible module-level consoles.  Legacy code and tests patch
# these names; rendering actually flows through wrapper/renderers consoles now.
console = Console()
err_console = Console(stderr=True)


def _config_data_for_display(config) -> dict:
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


def cmd_config_show(*, output: str = "text") -> None:
    config = load_config()
    ctx = build_command_context(
        command_name="config show",
        backend=None,
        config=config,
        output=output,
    )

    def action(_ctx: CommandContext):
        data = _config_data_for_display(_ctx.config)
        renderers.render_config_show(_ctx.render_ctx, data)

    execute(ctx, action)


def cmd_config_get(key: str, *, output: str = "text") -> None:
    config = load_config()
    ctx = build_command_context(
        command_name="config get",
        backend=None,
        config=config,
        output=output,
    )

    def action(_ctx: CommandContext):
        value = get_nested_value(_ctx.config, key)
        if value is None:
            raise InputError(f"Unknown config key: {key}")
        display = (
            redact_key(str(value))
            if ("api_key" in key or "key" in key.split(".")[-1:])
            else str(value)
        )
        renderers.render_config_get(_ctx.render_ctx, key, display)

    execute(ctx, action)


def cmd_config_set(key: str, value: str, *, output: str = "text") -> None:
    config = load_config()
    ctx = build_command_context(
        command_name="config set",
        backend=None,
        config=config,
        output=output,
    )

    def action(_ctx: CommandContext):
        if not set_nested_value(_ctx.config, key, value):
            raise InputError(f"Unknown config key: {key}")
        save_config(_ctx.config)
        display = redact_key(value) if "key" in key else value
        renderers.render_config_set(_ctx.render_ctx, key, display)

    execute(ctx, action)

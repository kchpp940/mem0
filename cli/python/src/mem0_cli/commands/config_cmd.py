"""Config management commands — driven by registry descriptors."""

from __future__ import annotations

from mem0_cli.config import load_config
from mem0_cli.core.descriptors import CONFIG_GET, CONFIG_SET, CONFIG_SHOW
from mem0_cli.core.registry import run_command


def cmd_config_show(*, output: str = "text") -> None:
    config = load_config()
    run_command(
        CONFIG_SHOW,
        backend=None,
        config=config,
        output=output,
    )


def cmd_config_get(key: str, *, output: str = "text") -> None:
    config = load_config()
    run_command(
        CONFIG_GET,
        backend=None,
        config=config,
        output=output,
        payload_kwargs={"key": key},
    )


def cmd_config_set(key: str, value: str, *, output: str = "text") -> None:
    config = load_config()
    run_command(
        CONFIG_SET,
        backend=None,
        config=config,
        output=output,
        payload_kwargs={"key": key, "value": value},
    )

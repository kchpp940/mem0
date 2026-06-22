"""Utility commands: status, version, import — driven by registry descriptors."""

from __future__ import annotations

from mem0_cli import __version__
from mem0_cli.branding import BRAND_COLOR
from mem0_cli.core.descriptors import IMPORT, STATUS
from mem0_cli.core.registry import run_command


def cmd_version() -> None:
    from rich.console import Console

    Console().print(f"  [{BRAND_COLOR}]◆ Mem0[/] CLI v{__version__}")


def cmd_status(
    backend,
    *,
    config=None,
    user_id: str | None = None,
    agent_id: str | None = None,
    output: str = "text",
) -> None:
    run_command(
        STATUS,
        backend=backend,
        config=config,
        output=output,
        payload_kwargs={"user_id": user_id, "agent_id": agent_id},
    )


def cmd_import(
    backend,
    file_path: str,
    *,
    config=None,
    user_id: str | None = None,
    agent_id: str | None = None,
    output: str = "text",
) -> None:
    run_command(
        IMPORT,
        backend=backend,
        config=config,
        output=output,
        user_id=user_id,
        agent_id=agent_id,
        payload_kwargs={"file_path": file_path, "user_id": user_id, "agent_id": agent_id},
    )

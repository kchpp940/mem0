"""Entity management commands — driven by registry descriptors."""

from __future__ import annotations

from mem0_cli.core.descriptors import ENTITY_DELETE, ENTITY_LIST
from mem0_cli.core.registry import run_command


def cmd_entities_list(
    backend,
    entity_type: str,
    *,
    config=None,
    output: str = "table",
) -> None:
    run_command(
        ENTITY_LIST,
        backend=backend,
        config=config,
        output=output,
        payload_kwargs={"entity_type": entity_type},
    )


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
    run_command(
        ENTITY_DELETE,
        backend=backend,
        config=config,
        output=output,
        dry_run=dry_run,
        force=force,
        user_id=user_id,
        agent_id=agent_id,
        app_id=app_id,
        run_id=run_id,
        payload_kwargs={"dry_run": dry_run, "force": force},
    )

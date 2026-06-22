"""Memory CRUD commands using the new layered architecture.

Each command function here follows the same three-step pattern:

1. Build a :class:`CommandContext` from the CLI options.
2. Define an *action* that uses the layered helpers:
   - ``requests.build_*_payload`` for request construction
   - ``ctx.backend.*`` to call the backend
   - ``renderers.render_*`` to display the result
3. Pass the context + action to ``wrapper.execute()``.

Option parsing/validation is performed inside the request builders
(``core/requests.py``), not in the command function itself.  The
command function only passes through raw Typer option values.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from mem0_cli.core import renderers
from mem0_cli.core.options import (
    require_between,
    require_positive,
)
from mem0_cli.core.requests import (
    build_add_payload,
    build_delete_all_payload,
    build_delete_payload,
    build_list_payload,
    build_search_payload,
    build_update_payload,
)
from mem0_cli.core.wrapper import (
    CommandContext,
    build_command_context,
    confirm_destructive,
    execute,
)

# ── Backwards-compatible module-level consoles.  Legacy code and tests patch
# these names; rendering actually flows through wrapper/renderers consoles now.
console = Console()
err_console = Console(stderr=True)


def _stdin_is_piped() -> bool:
    """Backwards-compatible shim — tests patch this name."""

    from mem0_cli.core.options import stdin_is_piped

    return stdin_is_piped()

# ── add ───────────────────────────────────────────────────────────────────


def cmd_add(
    backend,
    text: str | None,
    *,
    config=None,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    messages: str | None = None,
    file: Path | None = None,
    metadata: str | None = None,
    immutable: bool = False,
    no_infer: bool = False,
    expires: str | None = None,
    categories: str | None = None,
    output: str = "text",
) -> None:
    ctx = build_command_context(
        command_name="add",
        backend=backend,
        config=config,
        output=output,
        user_id=user_id,
        agent_id=agent_id,
        app_id=app_id,
        run_id=run_id,
    )

    def action(_ctx: CommandContext):
        payload = build_add_payload(
            text=text,
            messages=messages,
            file=file,
            metadata=metadata,
            immutable=immutable,
            no_infer=no_infer,
            expires=expires,
            categories=categories,
            scope=_ctx.ids,
        )
        result = _ctx.backend.add(**payload)
        renderers.render_add_result(_ctx.render_ctx, result)

    execute(ctx, action, spinner="Adding memory...")


# ── search ────────────────────────────────────────────────────────────────


def cmd_search(
    backend,
    query: str,
    *,
    config=None,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    top_k: int = 10,
    threshold: float = 0.3,
    rerank: bool = False,
    keyword: bool = False,
    filter_json: str | None = None,
    fields: str | None = None,
    output: str = "text",
) -> None:
    require_positive(top_k, field="--top-k")
    require_between(threshold, field="--threshold", minimum=0.0, maximum=1.0)

    ctx = build_command_context(
        command_name="search",
        backend=backend,
        config=config,
        output=output,
        user_id=user_id,
        agent_id=agent_id,
        app_id=app_id,
        run_id=run_id,
    )

    def action(_ctx: CommandContext):
        payload = build_search_payload(
            query=query,
            top_k=top_k,
            threshold=threshold,
            rerank=rerank,
            keyword=keyword,
            filter_json=filter_json,
            fields=fields,
            scope=_ctx.ids,
        )
        results = _ctx.backend.search(**payload)
        renderers.render_search_results(_ctx.render_ctx, results)

    execute(ctx, action, spinner="Searching memories...")


# ── get ───────────────────────────────────────────────────────────────────


def cmd_get(
    backend,
    memory_id: str,
    *,
    config=None,
    output: str = "text",
) -> None:
    ctx = build_command_context(
        command_name="get",
        backend=backend,
        config=config,
        output=output,
    )

    def action(_ctx: CommandContext):
        result = _ctx.backend.get(memory_id)
        renderers.render_single_memory(_ctx.render_ctx, result)

    execute(ctx, action, spinner="Fetching memory...")


# ── list ────────────────────────────────────────────────────────────────


def cmd_list(
    backend,
    *,
    config=None,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
    category: str | None = None,
    after: str | None = None,
    before: str | None = None,
    output: str = "text",
) -> None:
    require_positive(page, field="--page")
    require_positive(page_size, field="--page-size")

    ctx = build_command_context(
        command_name="list",
        backend=backend,
        config=config,
        output=output,
        user_id=user_id,
        agent_id=agent_id,
        app_id=app_id,
        run_id=run_id,
    )

    def action(_ctx: CommandContext):
        payload = build_list_payload(
            page=page,
            page_size=page_size,
            category=category,
            after=after,
            before=before,
            scope=_ctx.ids,
        )
        results = _ctx.backend.list_memories(**payload)
        renderers.render_list_memories(_ctx.render_ctx, results)

    execute(ctx, action, spinner="Listing memories...")


# ── update ────────────────────────────────────────────────────────────────


def cmd_update(
    backend,
    memory_id: str,
    text: str | None = None,
    *,
    config=None,
    metadata: str | None = None,
    output: str = "text",
) -> None:
    ctx = build_command_context(
        command_name="update",
        backend=backend,
        config=config,
        output=output,
    )

    def action(_ctx: CommandContext):
        payload = build_update_payload(
            memory_id=memory_id,
            text=text,
            metadata=metadata,
        )
        result = _ctx.backend.update(**payload)
        renderers.render_update_result(_ctx.render_ctx, result, memory_id=memory_id)

    execute(ctx, action, spinner="Updating memory...")


# ── delete ──────────────────────────────────────────────────────────────


def cmd_delete(
    backend,
    memory_id: str,
    output: str = "text",
    *,
    config=None,
    force: bool = False,
    dry_run: bool = False,
) -> None:
    ctx = build_command_context(
        command_name="delete",
        backend=backend,
        config=config,
        output=output,
    )

    def action(_ctx: CommandContext):
        payload = build_delete_payload(memory_id=memory_id, dry_run=dry_run)
        if dry_run:
            result = {"id": memory_id, "dry_run": True, "would_delete": True}
        else:
            result = _ctx.backend.delete(**payload)
        renderers.render_delete_result(_ctx.render_ctx, result, memory_id=memory_id, dry_run=dry_run)

    execute(ctx, action, spinner="Deleting memory...")


# ── delete-all ────────────────────────────────────────────────────────────


def cmd_delete_all(
    backend,
    *,
    config=None,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    all_project: bool = False,
    all_: bool = False,
    force: bool = False,
    dry_run: bool = False,
    output: str = "text",
) -> None:
    ctx = build_command_context(
        command_name="delete_all",
        backend=backend,
        config=config,
        output=output,
        user_id=user_id,
        agent_id=agent_id,
        app_id=app_id,
        run_id=run_id,
    )

    def action(_ctx: CommandContext):
        project_wide = all_project or all_
        payload = build_delete_all_payload(
            scope=_ctx.ids,
            all_project=all_project,
            all_=all_,
            dry_run=dry_run,
        )
        confirm_destructive(
            _ctx,
            "Delete ALL matching memories (project-wide)?" if project_wide else "Delete ALL your memories?",
            force=force,
        )
        if dry_run:
            result = {"dry_run": True, "would_delete": True, "scope": payload}
        else:
            result = _ctx.backend.delete(**payload)
        renderers.render_delete_all_result(
            _ctx.render_ctx, result, project_wide=project_wide, dry_run=dry_run
        )

    execute(ctx, action, spinner="Deleting all memories...")

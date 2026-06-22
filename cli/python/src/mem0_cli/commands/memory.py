"""Memory CRUD commands — driven by :mod:`mem0_cli.core.registry` descriptors.

Each command function is a thin Typer-facing shim that collects CLI options
and delegates to :func:`~mem0_cli.core.registry.run_command` with the
appropriate descriptor and payload kwargs.
"""

from __future__ import annotations

from pathlib import Path

from mem0_cli.core.descriptors import ADD, DELETE, DELETE_ALL, GET, LIST, SEARCH, UPDATE
from mem0_cli.core.options import require_between, require_positive
from mem0_cli.core.registry import run_command


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
    run_command(
        ADD,
        backend=backend,
        config=config,
        output=output,
        user_id=user_id,
        agent_id=agent_id,
        app_id=app_id,
        run_id=run_id,
        payload_kwargs=dict(
            text=text,
            messages=messages,
            file=file,
            metadata=metadata,
            immutable=immutable,
            no_infer=no_infer,
            expires=expires,
            categories=categories,
        ),
    )


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
    run_command(
        SEARCH,
        backend=backend,
        config=config,
        output=output,
        user_id=user_id,
        agent_id=agent_id,
        app_id=app_id,
        run_id=run_id,
        payload_kwargs=dict(
            query=query,
            top_k=top_k,
            threshold=threshold,
            rerank=rerank,
            keyword=keyword,
            filter_json=filter_json,
            fields=fields,
        ),
    )


def cmd_get(
    backend,
    memory_id: str,
    *,
    config=None,
    output: str = "text",
) -> None:
    run_command(
        GET,
        backend=backend,
        config=config,
        output=output,
        payload_kwargs={"memory_id": memory_id},
    )


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
    run_command(
        LIST,
        backend=backend,
        config=config,
        output=output,
        user_id=user_id,
        agent_id=agent_id,
        app_id=app_id,
        run_id=run_id,
        payload_kwargs=dict(
            page=page,
            page_size=page_size,
            category=category,
            after=after,
            before=before,
        ),
    )


def cmd_update(
    backend,
    memory_id: str,
    text: str | None = None,
    *,
    config=None,
    metadata: str | None = None,
    output: str = "text",
) -> None:
    run_command(
        UPDATE,
        backend=backend,
        config=config,
        output=output,
        payload_kwargs=dict(memory_id=memory_id, text=text, metadata=metadata),
        renderer_extras=dict(memory_id=memory_id),
    )


def cmd_delete(
    backend,
    memory_id: str,
    output: str = "text",
    *,
    config=None,
    force: bool = False,
    dry_run: bool = False,
) -> None:
    run_command(
        DELETE,
        backend=backend,
        config=config,
        output=output,
        dry_run=dry_run,
        force=force,
        payload_kwargs=dict(memory_id=memory_id, dry_run=dry_run),
        renderer_extras=dict(memory_id=memory_id),
    )


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
    project_wide = all_project or all_
    run_command(
        DELETE_ALL,
        backend=backend,
        config=config,
        output=output,
        dry_run=dry_run,
        force=force,
        user_id=user_id,
        agent_id=agent_id,
        app_id=app_id,
        run_id=run_id,
        payload_kwargs=dict(all_project=all_project, all_=all_, dry_run=dry_run),
        renderer_extras=dict(project_wide=project_wide, dry_run=dry_run),
    )

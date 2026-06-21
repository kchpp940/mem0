"""Memory CRUD commands: add, search, get, list, update, delete."""

from __future__ import annotations

import json
import os
import stat as _stat_mod
import sys
import time as _time
from pathlib import Path

import typer
from mem0.schema.fields import (
    SCOPE_DISPLAY_NAMES,
    validate_expires,
)
from rich.console import Console

from mem0_cli.backend.base import Backend
from mem0_cli.branding import (
    print_info,
    print_scope,
    print_success,
    timed_status,
)
from mem0_cli.option_builder import (
    build_scope,
    parse_categories,
    parse_json_option,
    validate_page,
    validate_page_size,
    validate_threshold,
    validate_top_k,
)
from mem0_cli.output import OutputRenderer
from mem0_cli.result_normalizer import dedup_pending, extract_add_results

console = Console()
err_console = Console(stderr=True)


def _stdin_is_piped() -> bool:
    """Return True only when stdin is an actual pipe or file redirect."""
    from mem0_cli.state import is_agent_mode

    if is_agent_mode():
        return False
    try:
        mode = os.fstat(sys.stdin.fileno()).st_mode
        return _stat_mod.S_ISFIFO(mode) or _stat_mod.S_ISREG(mode)
    except Exception:
        return False


def _resolve_output(output: str) -> str:
    from mem0_cli.state import is_agent_mode

    if is_agent_mode():
        return "agent"
    return output


def cmd_add(
    backend: Backend,
    text: str | None,
    *,
    user_id: str | None,
    agent_id: str | None,
    app_id: str | None,
    run_id: str | None,
    messages: str | None,
    file: Path | None,
    metadata: str | None,
    immutable: bool,
    no_infer: bool,
    expires: str | None,
    categories: str | None,
    output: str = "text",
) -> None:
    """Add a memory."""
    from mem0_cli.state import set_current_command

    set_current_command("add")
    output = _resolve_output(output)
    scope = build_scope(user_id=user_id, agent_id=agent_id, app_id=app_id, run_id=run_id)
    renderer = OutputRenderer(console, output_format=output, command="add", scope=scope, err_console=err_console)

    msgs = None
    content = text

    if file:
        try:
            raw = Path(file).read_text()
            msgs = json.loads(raw)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            renderer.error(f"Failed to read file: {e}", error_code="file_error")
            raise typer.Exit(1) from None

    elif messages:
        try:
            msgs = json.loads(messages)
        except json.JSONDecodeError as e:
            renderer.error(f"Invalid JSON in --messages: {e}", error_code="validation")
            raise typer.Exit(1) from None

    elif not content and _stdin_is_piped():
        content = sys.stdin.read().strip()

    if not content and not msgs:
        renderer.error(
            "No content provided. Pass text, --messages, --file, or pipe via stdin.",
            error_code="validation",
        )
        raise typer.Exit(1)

    try:
        meta = parse_json_option(metadata, name="--metadata")
    except ValueError:
        renderer.error("Invalid JSON in --metadata.", error_code="validation")
        raise typer.Exit(1) from None

    cats = parse_categories(categories)

    if expires:
        try:
            validate_expires(expires)
        except ValueError as e:
            renderer.error(str(e), error_code="validation")
            raise typer.Exit(1) from None

    with timed_status(err_console, "Adding memory...") as ts:
        try:
            result = backend.add(
                content=content,
                messages=msgs,
                user_id=user_id,
                agent_id=agent_id,
                app_id=app_id,
                run_id=run_id,
                metadata=meta,
                immutable=immutable,
                infer=not no_infer,
                expires=expires,
                categories=cats,
            )
        except Exception as e:
            ts.error_msg = str(e)
            renderer.error(str(e))
            raise typer.Exit(1) from None

    if output == "quiet":
        return

    results_list = extract_add_results(result)
    deduped = dedup_pending(results_list)

    if output in ("json", "agent"):
        renderer.add_result(deduped)
        return

    console.print()
    print_scope(console, user_id=user_id, agent_id=agent_id, app_id=app_id, run_id=run_id)
    count = len(deduped)
    all_pending = count > 0 and all(r.get("status") == "PENDING" for r in deduped)
    if all_pending:
        print_success(
            console,
            f"Memory queued — {count} event{'s' if count != 1 else ''} pending",
        )
    else:
        print_success(
            console, f"Memory processed — {count} memor{'y' if count == 1 else 'ies'} extracted"
        )
    renderer.add_result(deduped)


def cmd_search(
    backend: Backend,
    query: str,
    *,
    user_id: str | None,
    agent_id: str | None,
    app_id: str | None,
    run_id: str | None,
    top_k: int,
    threshold: float,
    rerank: bool,
    keyword: bool,
    filter_json: str | None,
    fields: str | None,
    output: str = "text",
) -> None:
    """Search memories."""
    from mem0_cli.state import set_current_command

    set_current_command("search")
    output = _resolve_output(output)
    scope = build_scope(user_id=user_id, agent_id=agent_id, app_id=app_id, run_id=run_id)
    renderer = OutputRenderer(console, output_format=output, command="search", scope=scope, err_console=err_console)

    try:
        filters = parse_json_option(filter_json, name="--filter")
    except ValueError:
        renderer.error("Invalid JSON in --filter.", error_code="validation")
        raise typer.Exit(1) from None

    field_list = [f.strip() for f in fields.split(",")] if fields else None

    try:
        validate_top_k(top_k)
    except ValueError as e:
        renderer.error(str(e), error_code="validation")
        raise typer.Exit(1) from None

    try:
        validate_threshold(threshold)
    except ValueError as e:
        renderer.error(str(e), error_code="validation")
        raise typer.Exit(1) from None

    _start = _time.perf_counter()
    with timed_status(err_console, "Searching memories...") as _ts:
        try:
            results = backend.search(
                query,
                user_id=user_id,
                agent_id=agent_id,
                app_id=app_id,
                run_id=run_id,
                top_k=top_k,
                threshold=threshold,
                rerank=rerank,
                keyword=keyword,
                filters=filters,
                fields=field_list,
            )
        except Exception as e:
            renderer.error(str(e))
            raise typer.Exit(1) from None
    _elapsed = _time.perf_counter() - _start

    if output == "quiet":
        return

    renderer.set_duration(seconds=_elapsed)

    if output in ("json", "agent"):
        renderer.memory_list(results, show_score=True)
        return

    if results:
        renderer.memory_list(results, show_score=True)
    else:
        console.print()
        print_info(console, "No memories found matching your query.")
        console.print()


def cmd_get(backend: Backend, memory_id: str, *, output: str) -> None:
    """Get a specific memory by ID."""
    from mem0_cli.state import set_current_command

    set_current_command("get")
    output = _resolve_output(output)
    renderer = OutputRenderer(console, output_format=output, command="get", err_console=err_console)

    with timed_status(err_console, "Fetching memory...") as _ts:
        try:
            result = backend.get(memory_id)
        except Exception as e:
            renderer.error(str(e))
            raise typer.Exit(1) from None

    renderer.single_memory(result)


def cmd_list(
    backend: Backend,
    *,
    user_id: str | None,
    agent_id: str | None,
    app_id: str | None,
    run_id: str | None,
    page: int,
    page_size: int,
    category: str | None,
    after: str | None,
    before: str | None,
    output: str = "table",
) -> None:
    """List memories."""
    from mem0_cli.state import set_current_command

    set_current_command("list")
    output = _resolve_output(output)
    scope = build_scope(user_id=user_id, agent_id=agent_id, app_id=app_id, run_id=run_id)
    renderer = OutputRenderer(console, output_format=output, command="list", scope=scope, err_console=err_console)

    try:
        validate_page_size(page_size)
    except ValueError as e:
        renderer.error(str(e), error_code="validation")
        raise typer.Exit(1) from None

    try:
        validate_page(page)
    except ValueError as e:
        renderer.error(str(e), error_code="validation")
        raise typer.Exit(1) from None

    _start = _time.perf_counter()
    with timed_status(err_console, "Listing memories...") as _ts:
        try:
            results = backend.list_memories(
                user_id=user_id,
                agent_id=agent_id,
                app_id=app_id,
                run_id=run_id,
                page=page,
                page_size=page_size,
                category=category,
                after=after,
                before=before,
            )
        except Exception as e:
            renderer.error(str(e))
            raise typer.Exit(1) from None
    _elapsed = _time.perf_counter() - _start

    if output == "quiet":
        return

    renderer.set_duration(seconds=_elapsed)

    if output in ("json", "agent"):
        renderer.memory_list(results, page=page)
        return

    if results:
        renderer.memory_list(results, page=page)
    else:
        console.print()
        print_info(console, "No memories found.")
        console.print()


def cmd_update(
    backend: Backend,
    memory_id: str,
    text: str | None,
    *,
    metadata: str | None,
    output: str,
) -> None:
    """Update a memory."""
    from mem0_cli.state import set_current_command

    set_current_command("update")
    output = _resolve_output(output)
    renderer = OutputRenderer(console, output_format=output, command="update", err_console=err_console)

    try:
        meta = parse_json_option(metadata, name="--metadata")
    except ValueError:
        renderer.error("Invalid JSON in --metadata.", error_code="validation")
        raise typer.Exit(1) from None

    _start = _time.perf_counter()
    with timed_status(err_console, "Updating memory...") as _ts:
        try:
            result = backend.update(memory_id, content=text, metadata=meta)
        except Exception as e:
            renderer.error(str(e))
            raise typer.Exit(1) from None
    _elapsed = _time.perf_counter() - _start

    renderer.set_duration(seconds=_elapsed)

    if output in ("json", "agent"):
        renderer.single_memory(result)
    elif output != "quiet":
        print_success(console, f"Memory {memory_id[:8]} updated ({_elapsed:.2f}s)")


def cmd_delete(
    backend: Backend,
    memory_id: str,
    *,
    dry_run: bool = False,
    force: bool = False,
    output: str,
) -> None:
    """Delete a single memory by ID."""
    from mem0_cli.state import set_current_command

    set_current_command("delete")
    output = _resolve_output(output)
    renderer = OutputRenderer(console, output_format=output, command="delete", err_console=err_console)

    if dry_run:
        try:
            mem = backend.get(memory_id)
        except Exception as e:
            renderer.error(str(e))
            raise typer.Exit(1) from None
        renderer.single_memory(mem)
        print_info(console, "No changes made (dry run).")
        return

    _start = _time.perf_counter()
    with timed_status(err_console, "Deleting...") as _ts:
        try:
            backend.delete(memory_id=memory_id)
        except Exception as e:
            renderer.error(str(e))
            raise typer.Exit(1) from None
    _elapsed = _time.perf_counter() - _start

    renderer.set_duration(seconds=_elapsed)

    if output in ("json", "agent"):
        renderer.data({"id": memory_id, "deleted": True})
    elif output != "quiet":
        print_success(console, f"Memory {memory_id[:8]} deleted ({_elapsed:.2f}s)")


def cmd_delete_all(
    backend: Backend,
    *,
    force: bool,
    dry_run: bool = False,
    all_: bool = False,
    user_id: str | None,
    agent_id: str | None,
    app_id: str | None,
    run_id: str | None,
    output: str,
) -> None:
    """Delete all memories matching a scope."""
    from mem0_cli.state import is_agent_mode, set_current_command

    set_current_command("delete-all")
    output = _resolve_output(output)
    scope = build_scope(user_id=user_id, agent_id=agent_id, app_id=app_id, run_id=run_id)
    renderer = OutputRenderer(console, output_format=output, command="delete-all", scope=scope, err_console=err_console)

    if is_agent_mode() and not force:
        renderer.error("Destructive operation requires --force in agent mode.", error_code="auth")
        raise typer.Exit(1)

    if all_:
        if not force:
            confirm = typer.confirm(
                "\n  ⚠  Delete ALL memories across the ENTIRE project? This cannot be undone."
            )
            if not confirm:
                print_info(console, "Cancelled.")
                raise typer.Exit(0)

        _start = _time.perf_counter()
        with timed_status(err_console, "Deleting all memories project-wide...") as _ts:
            try:
                result = backend.delete(
                    all=True,
                    user_id="*",
                    agent_id="*",
                    app_id="*",
                    run_id="*",
                )
            except Exception as e:
                renderer.error(str(e))
                raise typer.Exit(1) from None
        _elapsed = _time.perf_counter() - _start

        renderer.set_duration(seconds=_elapsed)

        if output in ("json", "agent"):
            renderer.data({"deleted": True, "scope": "project"})
        elif output != "quiet":
            if isinstance(result, dict) and "message" in result:
                print_info(console, "Deletion started. Memories will be removed in the background.")
            else:
                print_success(console, f"All project memories deleted ({_elapsed:.2f}s)")
        return

    if dry_run:
        try:
            results = backend.list_memories(
                user_id=user_id,
                agent_id=agent_id,
                app_id=app_id,
                run_id=run_id,
            )
        except Exception as e:
            renderer.error(str(e))
            raise typer.Exit(1) from None
        count = len(results)
        print_info(console, f"Would delete {count} memor{'y' if count == 1 else 'ies'}.")
        print_info(console, "No changes made (dry run).")
        return

    if not force:
        scope_parts = []
        entity_ids = {"user_id": user_id, "agent_id": agent_id, "app_id": app_id, "run_id": run_id}
        for field, value in entity_ids.items():
            if value:
                display_name = SCOPE_DISPLAY_NAMES.get(field, field)
                scope_parts.append(f"{display_name}={value}")
        scope_str = ", ".join(scope_parts) if scope_parts else "ALL entities"

        confirm = typer.confirm(f"\n  ⚠  Delete ALL memories for {scope_str}? This cannot be undone.")
        if not confirm:
            print_info(console, "Cancelled.")
            raise typer.Exit(0)

    _start = _time.perf_counter()
    with timed_status(err_console, "Deleting all memories...") as _ts:
        try:
            result = backend.delete(
                all=True,
                user_id=user_id,
                agent_id=agent_id,
                app_id=app_id,
                run_id=run_id,
            )
        except Exception as e:
            renderer.error(str(e))
            raise typer.Exit(1) from None
    _elapsed = _time.perf_counter() - _start

    renderer.set_duration(seconds=_elapsed)

    if output in ("json", "agent"):
        renderer.data({"deleted": True})
    elif output != "quiet":
        if isinstance(result, dict) and "message" in result:
            print_info(console, "Deletion started. Memories will be removed in the background.")
        else:
            print_success(console, f"All matching memories deleted ({_elapsed:.2f}s)")

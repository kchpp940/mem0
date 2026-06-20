"""Memory CRUD commands: add, search, get, list, update, delete."""

from __future__ import annotations

import json
import os
import stat as _stat_mod
import sys
import time as _time
from pathlib import Path

import typer
from rich.console import Console

from mem0_cli.backend.base import Backend
from mem0_cli.branding import (
    print_error,
    print_info,
    print_scope,
    print_success,
    timed_status,
)
from mem0_cli.output import (
    format_add_result,
    format_agent_envelope,
    format_json,
    format_memories_table,
    format_memories_text,
    format_single_memory,
    print_result_summary,
)

console = Console()
err_console = Console(stderr=True)


def _format_compact_trace(operation_id: str | None, trace: dict | None) -> str:
    """Build a compact one-line trace summary for CLI stderr output.

    Never prints raw text/prompts — only operation id, total duration,
    and per-stage name + duration + key non-sensitive statistics.
    """
    from rich.style import Style
    from rich.text import Text

    op_id_short = operation_id[:8] if operation_id else "?"

    if not trace:
        dim = Style(color="bright_black")
        t = Text()
        t.append("[trace] op=", style=dim)
        t.append(op_id_short, style=Style(bold=True, color="cyan"))
        t.append(f" · stages=0 · no_trace_data", style=dim)
        return t

    stages = trace.get("stages") or []
    total_ms = trace.get("total_duration_ms") or 0
    dim = Style(color="bright_black")
    accent = Style(color="cyan")
    accent2 = Style(color="bright_cyan")
    stage_style = Style(color="bright_blue")

    t = Text()
    t.append("[trace] op=", style=dim)
    t.append(op_id_short, style=Style(bold=True, color="cyan"))
    t.append(f" · total={total_ms:.0f}ms", style=dim)
    t.append(f" · stages={len(stages)}", style=dim)

    for s in stages:
        name = s.get("name", "?")
        dur = s.get("duration_ms")
        status = s.get("status", "ok")
        meta = s.get("metadata") or {}

        t.append(" | ", style=dim)
        t.append(name, style=stage_style)
        t.append(f":{dur:.0f}ms", style=accent)
        if status != "ok":
            t.append(f":{status}", style=Style(color="red", bold=True))

        # Pick a few high-signal non-sensitive keys
        picked: list[str] = []
        for key in (
            "count", "operation", "memories_added", "memories_updated",
            "memories_skipped", "duplicates_skipped", "entities_extracted",
            "entities_linked", "candidates_ranked", "candidates_passed_threshold",
            "semantic_candidates", "keyword_candidates", "entity_matches",
            "results_returned", "results_filtered", "has_bm25", "has_entity_boost",
            "threshold", "mode", "last_messages_count", "existing_memories",
        ):
            val = meta.get(key)
            if val is not None and val != "" and val != {} and val != []:
                if isinstance(val, bool):
                    picked.append(f"{key[:6]}={str(val)[0]}")
                else:
                    picked.append(f"{key[:6]}={val}")
        if picked:
            t.append("(" + ",".join(picked[:4]) + ")", style=accent2)

    return t


def _print_trace_epilogue(backend: Backend, operation_id: str | None, trace: dict | None) -> None:
    """Print the compact trace line to stderr."""
    # Fallback: if operation_id not provided, check backend.last_operation_id
    if operation_id is None:
        try:
            from mem0_cli.backend.platform import PlatformBackend
            if isinstance(backend, PlatformBackend):
                operation_id = backend.last_operation_id
        except Exception:
            pass

    compact = _format_compact_trace(operation_id, trace)
    err_console.print()
    err_console.print(compact)


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
    trace: bool = False,
) -> None:
    """Add a memory."""
    from mem0_cli.state import is_agent_mode, set_current_command

    set_current_command("add")
    if is_agent_mode():
        output = "agent"
    msgs = None
    content = text

    # Read from file
    if file:
        try:
            raw = Path(file).read_text()
            msgs = json.loads(raw)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print_error(err_console, f"Failed to read file: {e}")
            raise typer.Exit(1) from None

    # Parse messages JSON
    elif messages:
        try:
            msgs = json.loads(messages)
        except json.JSONDecodeError as e:
            print_error(err_console, f"Invalid JSON in --messages: {e}")
            raise typer.Exit(1) from None

    # Read from stdin only if stdin is an actual pipe or file redirect
    elif not content and _stdin_is_piped():
        content = sys.stdin.read().strip()

    if not content and not msgs:
        print_error(
            err_console, "No content provided. Pass text, --messages, --file, or pipe via stdin."
        )
        raise typer.Exit(1)

    meta = None
    if metadata:
        try:
            meta = json.loads(metadata)
        except json.JSONDecodeError:
            print_error(err_console, "Invalid JSON in --metadata.")
            raise typer.Exit(1) from None

    cats = None
    if categories:
        try:
            cats = json.loads(categories)
        except json.JSONDecodeError:
            cats = [c.strip() for c in categories.split(",")]

    # Validate --expires
    if expires:
        import re

        if not re.match(r"^\d{4}-\d{2}-\d{2}$", expires):
            print_error(
                err_console, "Invalid date format for --expires. Use YYYY-MM-DD (e.g. 2025-12-31)."
            )
            raise typer.Exit(1)
        from datetime import date

        if date.fromisoformat(expires) <= date.today():
            print_error(err_console, "--expires date must be in the future.")
            raise typer.Exit(1)

    # Extract trace metadata (non-sensitive) before sending content
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
                trace_enabled=trace,
            )
        except Exception as e:
            ts.error_msg = str(e)
            raise typer.Exit(1) from None

    # Extract trace info if present — always strip before formatters
    operation_id: str | None = None
    trace_data: dict | None = None
    if isinstance(result, dict):
        operation_id = result.get("operation_id")
        trace_data = result.get("trace") or result.get("trace_summary")
        # Remove trace fields so formatters see clean data
        result = {k: v for k, v in result.items() if k not in ("trace", "trace_summary")}

    if output == "quiet":
        if trace:
            _print_trace_epilogue(backend, operation_id, trace_data)
        return

    # Deduplicate PENDING entries sharing the same event_id across all output modes
    results_list = result if isinstance(result, list) else result.get("results", [result])
    seen_events: set[str] = set()
    deduped: list[dict] = []
    for r in results_list:
        if r.get("status") == "PENDING":
            eid = r.get("event_id", "")
            if eid and eid in seen_events:
                continue
            if eid:
                seen_events.add(eid)
        deduped.append(r)
    # Write back so downstream formatters see deduplicated data
    if isinstance(result, dict) and "results" in result:
        result = {**result, "results": deduped}
    else:
        result = deduped

    if output == "agent":
        scope = {
            k: v
            for k, v in {
                "user_id": user_id,
                "agent_id": agent_id,
                "app_id": app_id,
                "run_id": run_id,
            }.items()
            if v
        }
        agent_data = deduped
        if trace and operation_id:
            agent_data = {"results": deduped, "operation_id": operation_id}
            if trace_data:
                agent_data["trace"] = trace_data
        format_agent_envelope(
            console,
            command="add",
            data=agent_data,
            scope=scope or None,
            count=len(deduped),
        )
        if trace:
            _print_trace_epilogue(backend, operation_id, trace_data)
        return

    if output == "json":
        out_payload: Any = result
        if trace and operation_id:
            if isinstance(out_payload, dict):
                out_payload["operation_id"] = operation_id
                if trace_data:
                    out_payload["trace"] = trace_data
            else:
                out_payload = {
                    "results": out_payload,
                    "operation_id": operation_id,
                }
                if trace_data:
                    out_payload["trace"] = trace_data
        format_json(console, out_payload)
        if trace:
            _print_trace_epilogue(backend, operation_id, trace_data)
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
    format_add_result(console, result, output)

    if trace:
        _print_trace_epilogue(backend, operation_id, trace_data)


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
    trace: bool = False,
) -> None:
    """Search memories."""
    from mem0_cli.state import is_agent_mode, set_current_command

    set_current_command("search")
    if is_agent_mode():
        output = "agent"
    filters = None
    if filter_json:
        try:
            filters = json.loads(filter_json)
        except json.JSONDecodeError:
            print_error(err_console, "Invalid JSON in --filter.")
            raise typer.Exit(1) from None

    field_list = None
    if fields:
        field_list = [f.strip() for f in fields.split(",")]

    if top_k < 1:
        print_error(err_console, "--top-k must be >= 1.")
        raise typer.Exit(1)
    if not (0.0 <= threshold <= 1.0):
        print_error(err_console, "--threshold must be between 0.0 and 1.0.")
        raise typer.Exit(1)

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
                trace_enabled=trace,
            )
        except Exception as e:
            print_error(err_console, str(e))
            raise typer.Exit(1) from None
    _elapsed = _time.perf_counter() - _start

    # Unpack trace wrapper when trace is enabled
    operation_id: str | None = None
    trace_data: dict | None = None
    if isinstance(results, dict):
        operation_id = results.get("operation_id")
        trace_data = results.get("trace") or results.get("trace_summary")
        # Extract actual memories list
        results = results.get("results") or results.get("memories") or []

    if output == "quiet":
        if trace:
            _print_trace_epilogue(backend, operation_id, trace_data)
        return

    if output == "agent":
        scope = {
            k: v
            for k, v in {
                "user_id": user_id,
                "agent_id": agent_id,
                "app_id": app_id,
                "run_id": run_id,
            }.items()
            if v
        }
        agent_data: Any = results
        if trace and operation_id:
            agent_data = {"results": results, "operation_id": operation_id}
            if trace_data:
                agent_data["trace"] = trace_data
        format_agent_envelope(
            console,
            command="search",
            data=agent_data,
            scope=scope or None,
            count=len(results),
            duration_ms=int(_elapsed * 1000),
        )
        if trace:
            _print_trace_epilogue(backend, operation_id, trace_data)
        return

    if output == "json":
        out_payload: Any = results
        if trace and operation_id:
            if isinstance(out_payload, list):
                out_payload = {
                    "results": out_payload,
                    "operation_id": operation_id,
                }
                if trace_data:
                    out_payload["trace"] = trace_data
            else:
                out_payload["operation_id"] = operation_id
                if trace_data:
                    out_payload["trace"] = trace_data
        format_json(console, out_payload)
    elif output == "table":
        if results:
            format_memories_table(console, results, show_score=True)
            print_result_summary(
                console, len(results), duration_secs=_elapsed, user_id=user_id, agent_id=agent_id
            )
        else:
            console.print()
            print_info(console, "No memories found matching your query.")
            console.print()
    else:
        if results:
            format_memories_text(console, results)
            print_result_summary(
                console, len(results), duration_secs=_elapsed, user_id=user_id, agent_id=agent_id
            )
        else:
            console.print()
            print_info(console, "No memories found matching your query.")
            console.print()

    if trace:
        _print_trace_epilogue(backend, operation_id, trace_data)


def cmd_get(backend: Backend, memory_id: str, *, output: str) -> None:
    """Get a specific memory by ID."""
    from mem0_cli.state import is_agent_mode, set_current_command

    set_current_command("get")
    if is_agent_mode():
        output = "agent"
    with timed_status(err_console, "Fetching memory...") as _ts:
        try:
            result = backend.get(memory_id)
        except Exception as e:
            print_error(err_console, str(e))
            raise typer.Exit(1) from None

    if output == "agent":
        format_agent_envelope(console, command="get", data=result)
    else:
        format_single_memory(console, result, output)


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
    trace: bool = False,
) -> None:
    """List memories."""
    from mem0_cli.state import is_agent_mode, set_current_command

    set_current_command("list")
    if is_agent_mode():
        output = "agent"
    if page_size < 1:
        print_error(err_console, "--page-size must be >= 1.")
        raise typer.Exit(1)
    if page < 1:
        print_error(err_console, "--page must be >= 1.")
        raise typer.Exit(1)

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
                trace_enabled=trace,
            )
        except Exception as e:
            print_error(err_console, str(e))
            raise typer.Exit(1) from None
    _elapsed = _time.perf_counter() - _start

    # Unpack trace wrapper when trace is enabled
    operation_id: str | None = None
    trace_data: dict | None = None
    if isinstance(results, dict):
        operation_id = results.get("operation_id")
        trace_data = results.get("trace") or results.get("trace_summary")
        # Extract actual memories list
        results = results.get("results") or results.get("memories") or []

    if output == "quiet":
        if trace:
            _print_trace_epilogue(backend, operation_id, trace_data)
        return

    if output in ("json", "agent"):
        scope = {
            k: v
            for k, v in {
                "user_id": user_id,
                "agent_id": agent_id,
                "app_id": app_id,
                "run_id": run_id,
            }.items()
            if v
        }
        out_data: Any = results
        if trace and operation_id:
            out_data = {"results": results, "operation_id": operation_id}
            if trace_data:
                out_data["trace"] = trace_data
        format_agent_envelope(
            console,
            command="list",
            data=out_data,
            scope=scope or None,
            count=len(results),
            duration_ms=int(_elapsed * 1000),
        )
    elif output == "table":
        if results:
            format_memories_table(console, results)
            print_result_summary(
                console,
                len(results),
                duration_secs=_elapsed,
                page=page,
                user_id=user_id,
                agent_id=agent_id,
            )
        else:
            console.print()
            print_info(console, "No memories found.")
            console.print()
    else:
        if results:
            format_memories_text(console, results, title="memories")
            print_result_summary(
                console,
                len(results),
                duration_secs=_elapsed,
                page=page,
                user_id=user_id,
                agent_id=agent_id,
            )
        else:
            console.print()
            print_info(console, "No memories found.")
            console.print()

    if trace:
        _print_trace_epilogue(backend, operation_id, trace_data)


def cmd_update(
    backend: Backend,
    memory_id: str,
    text: str | None,
    *,
    metadata: str | None,
    output: str,
) -> None:
    """Update a memory."""
    from mem0_cli.state import is_agent_mode, set_current_command

    set_current_command("update")
    if is_agent_mode():
        output = "agent"
    meta = None
    if metadata:
        try:
            meta = json.loads(metadata)
        except json.JSONDecodeError:
            print_error(err_console, "Invalid JSON in --metadata.")
            raise typer.Exit(1) from None

    _start = _time.perf_counter()
    with timed_status(err_console, "Updating memory...") as _ts:
        try:
            result = backend.update(memory_id, content=text, metadata=meta)
        except Exception as e:
            print_error(err_console, str(e))
            raise typer.Exit(1) from None
    _elapsed = _time.perf_counter() - _start

    if output == "agent":
        format_agent_envelope(
            console,
            command="update",
            data=result,
            duration_ms=int(_elapsed * 1000),
        )
    elif output == "json":
        format_json(console, result)
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
    from mem0_cli.state import is_agent_mode, set_current_command

    set_current_command("delete")
    if is_agent_mode():
        output = "agent"
    if dry_run:
        # Fetch and display what would be deleted
        try:
            mem = backend.get(memory_id)
        except Exception as e:
            print_error(err_console, str(e))
            raise typer.Exit(1) from None
        format_single_memory(console, mem, output)
        print_info(console, "No changes made (dry run).")
        return

    _start = _time.perf_counter()
    with timed_status(err_console, "Deleting...") as _ts:
        try:
            result = backend.delete(memory_id=memory_id)
        except Exception as e:
            print_error(err_console, str(e))
            raise typer.Exit(1) from None
    _elapsed = _time.perf_counter() - _start

    if output == "agent":
        format_agent_envelope(
            console,
            command="delete",
            data={"id": memory_id, "deleted": True},
            duration_ms=int(_elapsed * 1000),
        )
    elif output == "json":
        format_json(console, result)
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
    if is_agent_mode():
        output = "agent"
        if not force:
            print_error(err_console, "Destructive operation requires --force in agent mode.")
            raise typer.Exit(1)
    if all_:
        # Project-wide wipe using wildcard entity IDs
        # Note: --dry-run is ignored here because the API has no count-before-delete endpoint.

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
                print_error(err_console, str(e))
                raise typer.Exit(1) from None
        _elapsed = _time.perf_counter() - _start

        if output == "agent":
            format_agent_envelope(
                console,
                command="delete-all",
                data={"deleted": True, "scope": "project"},
                duration_ms=int(_elapsed * 1000),
            )
        elif output == "json":
            format_json(console, result)
        elif output != "quiet":
            if isinstance(result, dict) and "message" in result:
                print_info(console, "Deletion started. Memories will be removed in the background.")
            else:
                print_success(console, f"All project memories deleted ({_elapsed:.2f}s)")
        return

    if dry_run:
        # List matching memories and show count
        try:
            results = backend.list_memories(
                user_id=user_id,
                agent_id=agent_id,
                app_id=app_id,
                run_id=run_id,
            )
        except Exception as e:
            print_error(err_console, str(e))
            raise typer.Exit(1) from None
        count = len(results)
        print_info(console, f"Would delete {count} memor{'y' if count == 1 else 'ies'}.")
        print_info(console, "No changes made (dry run).")
        return

    if not force:
        scope_parts = []
        if user_id:
            scope_parts.append(f"user={user_id}")
        if agent_id:
            scope_parts.append(f"agent={agent_id}")
        if app_id:
            scope_parts.append(f"app={app_id}")
        if run_id:
            scope_parts.append(f"run={run_id}")
        scope = ", ".join(scope_parts) if scope_parts else "ALL entities"

        confirm = typer.confirm(f"\n  ⚠  Delete ALL memories for {scope}? This cannot be undone.")
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
            print_error(err_console, str(e))
            raise typer.Exit(1) from None
    _elapsed = _time.perf_counter() - _start

    scope = {
        k: v
        for k, v in {
            "user_id": user_id,
            "agent_id": agent_id,
            "app_id": app_id,
            "run_id": run_id,
        }.items()
        if v
    }
    if output == "agent":
        format_agent_envelope(
            console,
            command="delete-all",
            data={"deleted": True},
            scope=scope or None,
            duration_ms=int(_elapsed * 1000),
        )
    elif output == "json":
        format_json(console, result)
    elif output != "quiet":
        if isinstance(result, dict) and "message" in result:
            print_info(console, "Deletion started. Memories will be removed in the background.")
        else:
            print_success(console, f"All matching memories deleted ({_elapsed:.2f}s)")

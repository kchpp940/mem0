"""Memory CRUD commands: add, search, get, list, update, delete, import, export."""

from __future__ import annotations

import csv
import json
import os
import stat as _stat_mod
import sys
import time as _time
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from mem0_cli.backend.base import Backend
from mem0_cli.branding import (
    DIM_COLOR,
    ERROR_COLOR,
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
            raise typer.Exit(1) from None

    if output == "quiet":
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
        format_agent_envelope(
            console,
            command="add",
            data=deduped,
            scope=scope or None,
            count=len(deduped),
        )
        return

    if output == "json":
        format_add_result(console, result, output)
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
            )
        except Exception as e:
            print_error(err_console, str(e))
            raise typer.Exit(1) from None
    _elapsed = _time.perf_counter() - _start

    if output == "quiet":
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
        format_agent_envelope(
            console,
            command="search",
            data=results,
            scope=scope or None,
            count=len(results),
            duration_ms=int(_elapsed * 1000),
        )
        return

    if output == "json":
        format_json(console, results)
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
            )
        except Exception as e:
            print_error(err_console, str(e))
            raise typer.Exit(1) from None
    _elapsed = _time.perf_counter() - _start

    if output == "quiet":
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
        format_agent_envelope(
            console,
            command="list",
            data=results,
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


# ── Import / Export helpers ────────────────────────────────────────────────


def _parse_field_map(field_map_str: str) -> dict[str, str]:
    """Parse field mapping string like 'content=memory,owner=user_id' into a dict."""
    mapping: dict[str, str] = {}
    if not field_map_str:
        return mapping
    for pair in field_map_str.split(","):
        if "=" in pair:
            src, dst = pair.split("=", 1)
            mapping[src.strip()] = dst.strip()
    return mapping


def _apply_field_map(item: dict[str, Any], field_map: dict[str, str]) -> dict[str, Any]:
    """Apply field mapping to transform source fields to destination fields."""
    if not field_map:
        return item
    mapped = dict(item)
    for src, dst in field_map.items():
        if src in mapped and src != dst:
            mapped[dst] = mapped.pop(src)
    return mapped


def _read_input_file(file_path: Path, format_hint: str | None = None) -> list[dict[str, Any]]:
    """Read JSONL, JSON, or CSV file and return list of dicts."""
    suffix = file_path.suffix.lower()
    if format_hint:
        suffix = f".{format_hint.lower()}"

    if suffix == ".jsonl":
        items: list[dict[str, Any]] = []
        with open(file_path) as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid JSONL at line {line_no}: {e}") from None
        return items

    if suffix == ".csv":
        with open(file_path, newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)

    # Default: JSON
    try:
        data = json.loads(file_path.read_text())
        if isinstance(data, list):
            return data
        return [data]
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from None


def _normalize_import_item(
    item: dict[str, Any],
    *,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    category: str | None = None,
    categories: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize an import item with CLI overrides and defaults."""
    normalized = dict(item)

    if user_id:
        normalized["user_id"] = user_id
    if agent_id:
        normalized["agent_id"] = agent_id
    if app_id:
        normalized["app_id"] = app_id
    if run_id:
        normalized["run_id"] = run_id

    if category:
        cats = normalized.get("categories", [])
        if isinstance(cats, str):
            cats = [c.strip() for c in cats.split(",")]
        if not isinstance(cats, list):
            cats = []
        if category not in cats:
            cats.append(category)
        normalized["categories"] = cats
    elif categories:
        normalized["categories"] = categories

    if metadata:
        existing_meta = normalized.get("metadata", {}) or {}
        if not isinstance(existing_meta, dict):
            existing_meta = {"value": existing_meta}
        existing_meta.update(metadata)
        normalized["metadata"] = existing_meta

    return normalized


def _format_preview_table(items: list[dict[str, Any]], max_rows: int = 10) -> Table:
    """Create a preview table for dry-run."""
    table = Table(title="Import Preview (first 10 rows)", show_header=True, header_style="bold")
    table.add_column("#", style=DIM_COLOR, width=4)
    table.add_column("Content", max_width=50)
    table.add_column("user_id", style="cyan")
    table.add_column("agent_id", style="magenta")
    table.add_column("categories", style="green")

    for i, item in enumerate(items[:max_rows]):
        content = item.get("memory") or item.get("text") or item.get("content") or ""
        if len(content) > 47:
            content = content[:47] + "..."
        table.add_row(
            str(i + 1),
            content,
            str(item.get("user_id", "")),
            str(item.get("agent_id", "")),
            ", ".join(item.get("categories", [])) if item.get("categories") else "",
        )

    if len(items) > max_rows:
        table.add_row("...", f"... and {len(items) - max_rows} more rows", "", "", "")

    return table


# ── Import command ────────────────────────────────────────────────────────


def cmd_import(
    backend: Backend,
    file_path: Path,
    *,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    category: str | None = None,
    categories: str | None = None,
    field_map: str | None = None,
    metadata: str | None = None,
    format: str | None = None,
    batch_size: int = 100,
    infer: bool = True,
    cursor: int = 0,
    resume: bool = False,
    dry_run: bool = False,
    output: str = "text",
) -> None:
    """Import memories from JSONL, JSON, or CSV files.

    Supports field mapping, category assignment, user/agent/run scope,
    batch processing with resumable cursor, and dry-run preview.
    """
    from mem0_cli.state import is_agent_mode, set_current_command

    set_current_command("import")
    if is_agent_mode():
        output = "agent"

    if not file_path.exists():
        print_error(err_console, f"File not found: {file_path}")
        raise typer.Exit(1) from None

    # Parse categories
    cats_list: list[str] | None = None
    if categories:
        try:
            cats_list = json.loads(categories)
        except json.JSONDecodeError:
            cats_list = [c.strip() for c in categories.split(",")]

    # Parse metadata
    meta_dict: dict[str, Any] | None = None
    if metadata:
        try:
            meta_dict = json.loads(metadata)
        except json.JSONDecodeError:
            print_error(err_console, "Invalid JSON in --metadata.")
            raise typer.Exit(1) from None

    # Parse field mapping
    mapping = _parse_field_map(field_map or "")

    try:
        items = _read_input_file(file_path, format)
    except ValueError as e:
        print_error(err_console, str(e))
        raise typer.Exit(1) from None

    total = len(items)
    if total == 0:
        print_info(console, "No items to import.")
        return

    # Apply field mapping and normalization
    items = [_apply_field_map(item, mapping) for item in items]
    items = [
        _normalize_import_item(
            item,
            user_id=user_id,
            agent_id=agent_id,
            app_id=app_id,
            run_id=run_id,
            category=category,
            categories=cats_list,
            metadata=meta_dict,
        )
        for item in items
    ]

    # Dry-run preview
    if dry_run:
        if output in ("json", "agent"):
            preview = {
                "total": total,
                "batch_size": batch_size,
                "cursor": cursor,
                "infer": infer,
                "field_map": mapping,
                "items": items[:10],
            }
            scope = {
                k: v
                for k, v in {
                    "user_id": user_id,
                    "agent_id": agent_id,
                    "app_id": app_id,
                    "run_id": run_id,
                    "category": category,
                }.items()
                if v
            }
            format_agent_envelope(
                console,
                command="import",
                data=preview,
                scope=scope or None,
                count=total,
            )
            return

        console.print()
        console.print(_format_preview_table(items))
        console.print()
        print_info(console, f"Total items: {total}")
        print_info(console, f"Batch size: {batch_size}")
        if mapping:
            print_info(console, f"Field mapping: {mapping}")
        print_info(console, "No changes made (dry run).")
        return

    # Resume from cursor
    if resume and cursor > 0:
        print_info(console, f"Resuming from cursor: {cursor}")

    _start = _time.perf_counter()
    total_success = 0
    total_failed = 0
    all_successful: list[dict[str, Any]] = []
    all_failed: list[dict[str, Any]] = []
    current_cursor = cursor

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=err_console,
    ) as progress:
        task = progress.add_task(f"Importing {total} memories...", total=total, completed=cursor)

        while current_cursor < total:
            batch_end = min(current_cursor + batch_size, total)
            batch_items = items[current_cursor:batch_end]

            try:
                result = backend.batch_import(
                    batch_items,
                    cursor=current_cursor,
                    batch_size=batch_size,
                    infer=infer,
                )
            except Exception as e:
                print_error(err_console, f"Batch import failed at cursor {current_cursor}: {e}")
                print_info(console, f"To resume, run with --resume --cursor {current_cursor}")
                raise typer.Exit(1) from None

            batch_success = result.get("success_count", 0)
            batch_failed = result.get("failed_count", 0)
            total_success += batch_success
            total_failed += batch_failed
            all_successful.extend(result.get("successful", []))
            all_failed.extend(result.get("failed", []))
            current_cursor = result.get("cursor", batch_end)

            progress.update(task, completed=current_cursor)

            if batch_failed > 0 and output == "text":
                progress.print(
                    f"  [{ERROR_COLOR}]![/] Batch had {batch_failed} failure(s)"
                )

    _elapsed = _time.perf_counter() - _start

    if output in ("json", "agent"):
        data = {
            "batch_id": result.get("batch_id") if "result" in locals() else None,
            "total": total,
            "processed": current_cursor,
            "success_count": total_success,
            "failed_count": total_failed,
            "cursor": current_cursor,
            "completed": current_cursor >= total,
            "successful": all_successful,
            "failed": all_failed,
        }
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
        format_agent_envelope(
            console,
            command="import",
            data=data,
            scope=scope or None,
            count=total,
            duration_ms=int(_elapsed * 1000),
        )
        return

    console.print()
    print_scope(console, user_id=user_id, agent_id=agent_id, app_id=app_id, run_id=run_id)
    print_success(
        console,
        f"Import complete — {total_success} succeeded, {total_failed} failed ({_elapsed:.2f}s)",
    )

    if current_cursor < total:
        print_info(console, f"To resume, run with --resume --cursor {current_cursor}")

    if all_failed and output == "text":
        console.print()
        console.print(f"[{ERROR_COLOR}]Failures:[/]")
        for f in all_failed[:10]:
            idx = f.get("index", "?")
            err = f.get("error", "unknown error")
            mem = (f.get("memory") or "")[:50]
            console.print(f"  [{DIM_COLOR}]#{idx}:[/] {err} — {mem}...")
        if len(all_failed) > 10:
            console.print(f"  [{DIM_COLOR}]... and {len(all_failed) - 10} more[/]")


# ── Export command ────────────────────────────────────────────────────────


def cmd_export(
    backend: Backend,
    output_file: Path,
    *,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    category: str | None = None,
    after: str | None = None,
    before: str | None = None,
    filter_json: str | None = None,
    format: str = "jsonl",
    output: str = "text",
) -> None:
    """Export memories to JSONL format with optional filters.

    Exports fields: id, memory, user_id, agent_id, run_id, metadata,
    created_at, updated_at, categories, feedback, feedback_reason.
    """
    from mem0_cli.state import is_agent_mode, set_current_command

    set_current_command("export")
    if is_agent_mode():
        output = "agent"

    filters: dict[str, Any] | None = None
    if filter_json:
        try:
            filters = json.loads(filter_json)
        except json.JSONDecodeError:
            print_error(err_console, "Invalid JSON in --filter.")
            raise typer.Exit(1) from None

    _start = _time.perf_counter()
    try:
        export_data = backend.export_memories(
            user_id=user_id,
            agent_id=agent_id,
            app_id=app_id,
            run_id=run_id,
            category=category,
            after=after,
            before=before,
            filters=filters,
        )
    except Exception as e:
        print_error(err_console, f"Export failed: {e}")
        raise typer.Exit(1) from None

    _elapsed = _time.perf_counter() - _start

    # Count exported items
    count = sum(1 for line in export_data.strip().split("\n") if line.strip())

    # Write to file
    try:
        output_file.write_text(export_data)
    except Exception as e:
        print_error(err_console, f"Failed to write output file: {e}")
        raise typer.Exit(1) from None

    if output in ("json", "agent"):
        data = {
            "file": str(output_file),
            "count": count,
            "format": format,
        }
        scope = {
            k: v
            for k, v in {
                "user_id": user_id,
                "agent_id": agent_id,
                "app_id": app_id,
                "run_id": run_id,
                "category": category,
            }.items()
            if v
        }
        format_agent_envelope(
            console,
            command="export",
            data=data,
            scope=scope or None,
            count=count,
            duration_ms=int(_elapsed * 1000),
        )
        return

    console.print()
    print_scope(console, user_id=user_id, agent_id=agent_id, app_id=app_id, run_id=run_id)
    print_success(
        console,
        f"Exported {count} memories to {output_file} ({_elapsed:.2f}s)",
    )

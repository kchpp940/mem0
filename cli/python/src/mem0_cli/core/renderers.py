"""Output renderers.

A :class:`Renderer` takes a :class:`RenderContext` and a *raw data payload*
from the backend, then emits the correct user-facing output for the active
output mode (text / table / json / quiet / agent-envelope).

Commands *never* branch on ``output`` themselves — they hand the backend
data to a renderer and move on.  Mode-specific detail (scope printing,
spinner timing, JSON sanitisation, count summaries) lives inside the
renderer so adding a new output mode only touches this module.
"""

from __future__ import annotations

import json as _json
import time as _time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from mem0_cli.branding import (
    ACCENT_COLOR,
    BRAND_COLOR,
    DIM_COLOR,
    ERROR_COLOR,
    SUCCESS_COLOR,
    WARNING_COLOR,
    _sym,
    print_info,
    print_scope,
    print_success,
)
from mem0_cli.core.console import err_console as _core_err_console
from mem0_cli.core.console import stdout_console as console

# ── Render context ────────────────────────────────────────────────────────


@dataclass
class RenderContext:
    """Immutable rendering parameters carried through a command.

    Only the execution wrapper constructs this; command functions read it
    and pass it to the renderer.
    """

    command_name: str
    output_mode: str
    scope: dict[str, str | None] = field(default_factory=dict)
    started_at: float = field(default_factory=_time.perf_counter)

    def elapsed_ms(self) -> int:
        return int((_time.perf_counter() - self.started_at) * 1000)

    def elapsed_s(self) -> float:
        return _time.perf_counter() - self.started_at

    def non_null_scope(self) -> dict[str, str]:
        return {k: v for k, v in self.scope.items() if v}


def resolve_output_mode(preferred: str, *, command_agent: bool = True) -> str:
    """Return the effective output mode honouring agent mode.

    Commands should call this *once* when constructing RenderContext.
    """

    from mem0_cli.state import is_agent_mode

    if command_agent and is_agent_mode():
        return "agent"
    return preferred


# ── Low-level building blocks (mirror output.py for consistency) ──────────


def _format_date(dt_str: str | None) -> str | None:
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return str(dt_str)[:10] if dt_str else None


def _emit_json(data: Any) -> None:
    console.print_json(_json.dumps(data, default=str))


# ── JSON sanitisation for agent mode ──────────────────────────────────────


def _pick(obj: dict, keys: list[str]) -> dict:
    return {k: obj[k] for k in keys if k in obj}


def _sanitize(command: str, data: Any) -> Any:
    if data is None:
        return data

    if command == "add":
        items = data if isinstance(data, list) else [data]
        out = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("status") == "PENDING":
                out.append(_pick(item, ["status", "event_id"]))
            else:
                out.append(_pick(item, ["id", "memory", "event"]))
        return out

    if command == "search":
        return [_pick(r, ["id", "memory", "score", "created_at", "categories"]) for r in data or []]

    if command == "list":
        return [_pick(r, ["id", "memory", "created_at", "categories"]) for r in data or []]

    if command == "get":
        return _pick(data, ["id", "memory", "created_at", "updated_at", "categories", "metadata"])

    if command == "update":
        return _pick(data, ["id", "memory"])

    if command in ("delete", "delete-all", "entity delete"):
        return data

    if command == "entity list":
        out = []
        for r in data or []:
            if not isinstance(r, dict):
                continue
            item = _pick(r, ["type", "count"])
            item["name"] = r.get("name") or r.get("id", "")
            out.append(item)
        return out

    if command == "event list":
        return [_pick(r, ["id", "event_type", "status", "latency", "created_at"]) for r in data or []]

    if command == "event status":
        ev = data if isinstance(data, dict) else {}
        raw_results = ev.get("results") or []
        sanitized_results = []
        for r in raw_results:
            if not isinstance(r, dict):
                continue
            nested = r.get("data") or {}
            memory = nested.get("memory") if isinstance(nested, dict) else None
            sanitized_results.append(
                {
                    "id": r.get("id"),
                    "event": r.get("event"),
                    "user_id": r.get("user_id"),
                    "memory": memory,
                }
            )
        result = _pick(ev, ["id", "event_type", "status", "latency", "created_at", "updated_at"])
        result["results"] = sanitized_results
        return result

    return data


def _agent_envelope(
    ctx: RenderContext,
    data: Any,
    *,
    count: int | None = None,
) -> None:
    envelope: dict[str, Any] = {
        "status": "success",
        "command": ctx.command_name,
    }
    dur = ctx.elapsed_ms()
    if dur >= 0:
        envelope["duration_ms"] = dur
    scope = ctx.non_null_scope()
    if scope:
        envelope["scope"] = scope
    if count is not None:
        envelope["count"] = count
    envelope["data"] = _sanitize(ctx.command_name, data)

    from mem0_cli.state import take_notice

    notice = take_notice()
    if notice:
        envelope["mem0_notice"] = notice

    _emit_json(envelope)


# ── Generic Renderer API ──────────────────────────────────────────────────


RendererFn = Callable[[RenderContext, Any], None]


def render_list_memories(ctx: RenderContext, memories: list[dict]) -> None:
    if ctx.output_mode == "quiet":
        return

    if ctx.output_mode == "agent":
        _agent_envelope(ctx, memories, count=len(memories))
        return

    if ctx.output_mode == "json":
        _emit_json(memories)
        return

    if not memories:
        print_info(console, "No memories found.")
        return

    if ctx.output_mode == "table":
        _render_memories_table(memories, show_score=False)
        _render_list_summary(ctx, len(memories))
    else:
        _render_memories_text(memories, title="memories")
        _render_list_summary(ctx, len(memories))


def render_search_results(ctx: RenderContext, results: list[dict]) -> None:
    if ctx.output_mode == "quiet":
        return

    if ctx.output_mode == "agent":
        _agent_envelope(ctx, results, count=len(results))
        return

    if ctx.output_mode == "json":
        _emit_json(results)
        return

    if not results:
        console.print()
        print_info(console, "No memories found matching your query.")
        console.print()
        return

    if ctx.output_mode == "table":
        _render_memories_table(results, show_score=True)
        _render_list_summary(ctx, len(results))
    else:
        _render_memories_text(results)
        _render_list_summary(ctx, len(results))


def render_single_memory(ctx: RenderContext, mem: dict) -> None:
    if ctx.output_mode == "agent":
        _agent_envelope(ctx, mem)
        return

    if ctx.output_mode == "json":
        _emit_json(mem)
        return

    memory_text = mem.get("memory", mem.get("text", ""))
    mem_id = mem.get("id", "")

    lines = [
        f"  [white bold]{memory_text}[/]",
        "",
    ]
    if mem_id:
        lines.append(f"  [{DIM_COLOR}]ID:[/]         {mem_id}")
    created = _format_date(mem.get("created_at"))
    if created:
        lines.append(f"  [{DIM_COLOR}]Created:[/]    {created}")
    updated = _format_date(mem.get("updated_at"))
    if updated:
        lines.append(f"  [{DIM_COLOR}]Updated:[/]    {updated}")
    meta = mem.get("metadata")
    if meta:
        lines.append(f"  [{DIM_COLOR}]Metadata:[/]   {_json.dumps(meta)}")
    categories = mem.get("categories")
    if categories:
        cat_str = ", ".join(categories) if isinstance(categories, list) else categories
        lines.append(f"  [{DIM_COLOR}]Categories:[/] {cat_str}")

    panel = Panel(
        "\n".join(lines),
        title=f"[{BRAND_COLOR}]Memory[/]",
        title_align="left",
        border_style=BRAND_COLOR,
        padding=(1, 1),
    )
    console.print()
    console.print(panel)
    console.print()


def render_add_result(ctx: RenderContext, result: dict | list) -> None:
    if ctx.output_mode == "quiet":
        return

    # De-duplicate PENDING entries by event_id
    results_list = result if isinstance(result, list) else result.get("results", [result])
    seen_events: set[str] = set()
    deduped: list[dict] = []
    for r in results_list:
        if not isinstance(r, dict):
            continue
        if r.get("status") == "PENDING":
            eid = r.get("event_id", "")
            if eid and eid in seen_events:
                continue
            if eid:
                seen_events.add(eid)
        deduped.append(r)

    if ctx.output_mode == "agent":
        _agent_envelope(ctx, deduped, count=len(deduped))
        return

    if ctx.output_mode == "json":
        payload = {**result, "results": deduped} if isinstance(result, dict) and "results" in result else deduped
        _emit_json(payload)
        return

    console.print()
    print_scope(console, **ctx.scope)
    count = len(deduped)
    all_pending = count > 0 and all(isinstance(r, dict) and r.get("status") == "PENDING" for r in deduped)
    if all_pending:
        print_success(
            console,
            f"Memory queued — {count} event{'s' if count != 1 else ''} pending",
        )
    else:
        print_success(
            console, f"Memory processed — {count} memor{'y' if count == 1 else 'ies'} extracted"
        )
    _render_add_items(deduped)


def render_update_result(ctx: RenderContext, result: dict, memory_id: str) -> None:
    if ctx.output_mode == "agent":
        _agent_envelope(ctx, result)
        return
    if ctx.output_mode == "json":
        _emit_json(result)
        return
    if ctx.output_mode == "quiet":
        return
    print_success(console, f"Memory {str(memory_id)[:8]} updated ({ctx.elapsed_s():.2f}s)")


def render_delete_result(
    ctx: RenderContext,
    result: dict | bool,
    memory_id: str,
    *,
    dry_run: bool = False,
) -> None:
    if ctx.output_mode == "agent":
        _agent_envelope(ctx, {"id": memory_id, "deleted": not dry_run, "dry_run": dry_run})
        return
    if ctx.output_mode == "json":
        _emit_json(result)
        return
    if ctx.output_mode == "quiet":
        return
    if dry_run:
        print_info(console, f"Dry run: memory {str(memory_id)[:8]} would be deleted")
    else:
        print_success(console, f"Memory {str(memory_id)[:8]} deleted ({ctx.elapsed_s():.2f}s)")


def render_delete_all_result(
    ctx: RenderContext,
    result: dict,
    *,
    project_wide: bool,
    dry_run: bool = False,
) -> None:
    scope_label = "project" if project_wide else "scope"
    if ctx.output_mode == "agent":
        _agent_envelope(ctx, {"deleted": not dry_run, "scope": scope_label, "dry_run": dry_run})
        return
    if ctx.output_mode == "json":
        _emit_json(result)
        return
    if ctx.output_mode == "quiet":
        return
    if isinstance(result, dict) and "message" in result:
        print_info(console, "Deletion started. Memories will be removed in the background.")
    elif dry_run:
        if project_wide:
            print_info(console, "Dry run: all project memories would be deleted")
        else:
            print_info(console, "Dry run: all matching memories would be deleted")
    elif project_wide:
        print_success(console, f"All project memories deleted ({ctx.elapsed_s():.2f}s)")
    else:
        print_success(console, f"All matching memories deleted ({ctx.elapsed_s():.2f}s)")


def render_status(ctx: RenderContext, result: dict) -> None:
    if ctx.output_mode in ("json", "agent"):
        connected = bool(result.get("connected", False))
        data = {
            "status": "connected" if connected else "disconnected",
            "connected": connected,
            "backend": result.get("backend", "?"),
            "base_url": result.get("base_url", ""),
        }
        if ctx.output_mode == "agent":
            _agent_envelope(ctx, data)
        else:
            _emit_json(data)
        return

    lines = []
    if result.get("connected"):
        lines.append(f"  [{SUCCESS_COLOR}]●[/] Connected")
    else:
        lines.append(f"  [{ERROR_COLOR}]●[/] Disconnected")
    lines.append(f"  [{DIM_COLOR}]Backend:[/]  {result.get('backend', '?')}")
    if result.get("base_url"):
        lines.append(f"  [{DIM_COLOR}]API URL:[/]  {result['base_url']}")
    if result.get("error"):
        lines.append(f"  [{ERROR_COLOR}]Error:[/]    {result['error']}")
        if "Authentication failed" in str(result["error"]):
            lines.append("")
            lines.append(
                f"  [{DIM_COLOR}]Run [bold]mem0 init[/bold] to reconfigure your API key[/]"
            )
    lines.append(f"  [{DIM_COLOR}]Latency:[/]  {ctx.elapsed_s():.2f}s")

    panel = Panel(
        "\n".join(lines),
        title=f"[{BRAND_COLOR}]Connection Status[/]",
        title_align="left",
        border_style=BRAND_COLOR,
        padding=(1, 1),
    )
    console.print()
    console.print(panel)
    console.print()


def render_config_show(ctx: RenderContext, config_data: dict) -> None:
    if ctx.output_mode in ("json", "agent"):
        data = {
            "status": "ok",
            "command": "config show",
            **config_data,
        }
        if ctx.output_mode == "agent":
            _agent_envelope(ctx, data)
        else:
            _emit_json(data)
        return

    console.print()
    console.print(f"  [{BRAND_COLOR}]◆ mem0 Configuration[/]\n")

    table = Table(border_style=BRAND_COLOR, header_style=f"bold {ACCENT_COLOR}", padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")

    defaults = config_data.get("defaults", {})
    for k in ("user_id", "agent_id", "app_id", "run_id"):
        table.add_row(
            f"defaults.{k}",
            defaults.get(k) or f"[{DIM_COLOR}](not set)[/]",
        )
    table.add_row("", "")

    platform = config_data.get("platform", {})
    table.add_row("[bold]platform.api_key[/]", platform.get("api_key") or f"[{DIM_COLOR}](not set)[/]")
    table.add_row("platform.base_url", platform.get("base_url") or f"[{DIM_COLOR}](default)[/]")

    console.print(table)
    console.print()


def render_config_get(ctx: RenderContext, key: str, value: str) -> None:
    if ctx.output_mode in ("json", "agent"):
        data = {"key": key, "value": value}
        if ctx.output_mode == "agent":
            _agent_envelope(ctx, data)
        else:
            _emit_json(data)
        return
    console.print(value)


def render_config_set(ctx: RenderContext, key: str, value: str) -> None:
    if ctx.output_mode == "agent":
        _agent_envelope(ctx, {"key": key, "value": value})
        return
    print_success(console, f"{key} = {value}")


def render_import(ctx: RenderContext, added: int, failed: int) -> None:
    if ctx.output_mode in ("json", "agent"):
        data = {"added": added, "failed": failed}
        if ctx.output_mode == "agent":
            _agent_envelope(ctx, data)
        else:
            _emit_json(data)
        return
    err = _core_err_console
    print_success(err, f"Imported {added} memories ({ctx.elapsed_s():.2f}s)")
    if failed:
        from mem0_cli.branding import print_error as _print_err

        _print_err(err, f"{failed} memories failed to import.")


def render_entity_list(ctx: RenderContext, entity_type: str, results: list[dict]) -> None:
    if ctx.output_mode == "agent":
        _agent_envelope(ctx, results, count=len(results))
        return
    if ctx.output_mode == "json":
        _emit_json(results)
        return
    if not results:
        print_info(console, f"No {entity_type} found.")
        return

    table = Table(border_style=BRAND_COLOR, header_style=f"bold {ACCENT_COLOR}", padding=(0, 1))
    table.add_column("Name / ID", style="bold")
    table.add_column("Created", max_width=12)

    for entity in results:
        name = entity.get("name", entity.get("id", "—"))
        created = str(entity.get("created_at", "—"))[:10]
        table.add_row(str(name), created)

    console.print()
    console.print(table)
    console.print(f"  [{DIM_COLOR}]{len(results)} {entity_type} ({ctx.elapsed_s():.2f}s)[/]")
    console.print()


def render_entity_delete(ctx: RenderContext, result: dict, *, dry_run: bool = False) -> None:
    if dry_run:
        if ctx.output_mode == "agent":
            _agent_envelope(ctx, {"dry_run": True, "deleted": False})
            return
        if ctx.output_mode == "json":
            _emit_json({"dry_run": True, "changes": "none"})
            return
        if ctx.output_mode == "quiet":
            return
        console.print()
        print_info(console, "Would delete the entity and all its memories.")
        print_info(console, "No changes made (dry run).")
        console.print()
        return

    if ctx.output_mode == "agent":
        _agent_envelope(ctx, {"deleted": True})
        return
    if ctx.output_mode == "json":
        _emit_json(result)
        return
    if ctx.output_mode == "quiet":
        return
    print_success(console, f"Entity deleted with all memories ({ctx.elapsed_s():.2f}s)")


_STATUS_STYLE = {
    "SUCCEEDED": f"[{SUCCESS_COLOR}]SUCCEEDED[/]",
    "PENDING": f"[{ACCENT_COLOR}]PENDING[/]",
    "FAILED": f"[{ERROR_COLOR}]FAILED[/]",
    "PROCESSING": f"[{WARNING_COLOR}]PROCESSING[/]",
}


def _status_styled(status: str) -> str:
    return _STATUS_STYLE.get(str(status).upper(), status)


def render_event_list(ctx: RenderContext, results: list[dict]) -> None:
    if ctx.output_mode == "agent":
        _agent_envelope(ctx, results, count=len(results))
        return
    if ctx.output_mode == "json":
        _emit_json(results)
        return
    if not results:
        console.print()
        print_info(console, "No events found.")
        console.print()
        return

    table = Table(
        border_style=BRAND_COLOR,
        header_style=f"bold {ACCENT_COLOR}",
        row_styles=["", "dim"],
        padding=(0, 1),
    )
    table.add_column("Event ID", style="dim", max_width=10, no_wrap=True)
    table.add_column("Type", max_width=14)
    table.add_column("Status", max_width=12)
    table.add_column("Latency", max_width=10, justify="right")
    table.add_column("Created", max_width=20)

    for ev in results:
        ev_id = str(ev.get("id", ""))[:8]
        ev_type = str(ev.get("event_type", "—"))
        status = str(ev.get("status", "—"))
        latency = ev.get("latency")
        latency_str = f"{latency:.0f}ms" if isinstance(latency, (int, float)) else "—"
        created = str(ev.get("created_at", "—"))[:19].replace("T", " ")
        table.add_row(ev_id, ev_type, _status_styled(status), latency_str, created)

    console.print()
    console.print(table)
    console.print(f"  [{DIM_COLOR}]{len(results)} event{'s' if len(results) != 1 else ''}[/]")
    console.print()


def render_event_status(ctx: RenderContext, ev: dict) -> None:
    if ctx.output_mode == "agent":
        _agent_envelope(ctx, ev)
        return
    if ctx.output_mode == "json":
        _emit_json(ev)
        return

    status = str(ev.get("status", "—"))
    ev_type = str(ev.get("event_type", "—"))
    latency = ev.get("latency")
    latency_str = f"{latency:.0f}ms" if isinstance(latency, (int, float)) else "—"
    created = str(ev.get("created_at", "—"))[:19].replace("T", " ")
    updated = str(ev.get("updated_at", "—"))[:19].replace("T", " ")
    results = ev.get("results")

    lines = [
        f"  [{DIM_COLOR}]Event ID:[/]     {ev.get('id', '')}",
        f"  [{DIM_COLOR}]Type:[/]         {ev_type}",
        f"  [{DIM_COLOR}]Status:[/]       {_status_styled(status)}",
        f"  [{DIM_COLOR}]Latency:[/]      {latency_str}",
        f"  [{DIM_COLOR}]Created:[/]      {created}",
        f"  [{DIM_COLOR}]Updated:[/]      {updated}",
    ]
    if results:
        lines.append("")
        lines.append(f"  [{DIM_COLOR}]Results ({len(results)}):[/]")
        for r in results:
            if not isinstance(r, dict):
                continue
            mem_id = str(r.get("id", ""))[:8]
            data = r.get("data", {})
            memory = data.get("memory", "") if isinstance(data, dict) else str(data)
            ev_name = str(r.get("event", ""))
            user = str(r.get("user_id", ""))
            detail = f"{ev_name}  {memory}"
            if user:
                detail += f"  [{DIM_COLOR}](user_id={user})[/]"
            lines.append(f"    [{SUCCESS_COLOR}]·[/] {detail}  [{DIM_COLOR}]({mem_id})[/]")

    panel = Panel(
        "\n".join(lines),
        title=f"[{BRAND_COLOR}]Event Status[/]",
        title_align="left",
        border_style=BRAND_COLOR,
        padding=(1, 1),
    )
    console.print()
    console.print(panel)
    console.print()


# ── Private helpers ───────────────────────────────────────────────────────


def _render_memories_text(memories: list[dict], title: str = "memories") -> None:
    count = len(memories)
    console.print(f"\n[{BRAND_COLOR}]Found {count} {title}:[/]\n")
    for i, mem in enumerate(memories, 1):
        memory_text = mem.get("memory", mem.get("text", ""))
        mem_id = str(mem.get("id", ""))[:8]
        score = mem.get("score")
        created = _format_date(mem.get("created_at"))
        category = mem.get("categories", [None])
        if isinstance(category, list):
            category = category[0] if category else None

        line = Text()
        line.append(f"  {i}. ", style="bold")
        line.append(memory_text, style="white")
        console.print(line)

        details = []
        if score is not None:
            details.append(f"Score: {score:.2f}")
        if mem_id:
            details.append(f"ID: {mem_id}")
        if created:
            details.append(f"Created: {created}")
        if category:
            details.append(f"Category: {category}")
        if details:
            console.print(f"     [{DIM_COLOR}]{' · '.join(details)}[/]")
        console.print()


def _render_memories_table(memories: list[dict], *, show_score: bool) -> None:
    table = Table(
        border_style=BRAND_COLOR,
        header_style=f"bold {ACCENT_COLOR}",
        row_styles=["", "dim"],
        padding=(0, 1),
    )
    table.add_column("ID", style="dim", max_width=38, no_wrap=True)
    if show_score:
        table.add_column("Score", max_width=7, justify="right")
    table.add_column("Memory", max_width=50, no_wrap=False)
    table.add_column("Category", max_width=14)
    table.add_column("Created", max_width=12)

    for mem in memories:
        mem_id = mem.get("id", "")
        memory_text = mem.get("memory", mem.get("text", ""))
        if len(str(memory_text)) > 60:
            memory_text = str(memory_text)[:57] + "..."
        categories = mem.get("categories", [])
        if isinstance(categories, list) and categories:
            cat = (
                categories[0]
                if len(categories) == 1
                else f"{categories[0]} (+{len(categories) - 1})"
            )
        else:
            cat = "—"
        created = _format_date(mem.get("created_at")) or "—"
        if show_score:
            score = mem.get("score")
            score_str = f"{score:.2f}" if score is not None else "—"
            table.add_row(str(mem_id), score_str, str(memory_text), str(cat), str(created))
        else:
            table.add_row(str(mem_id), str(memory_text), str(cat), str(created))

    console.print()
    console.print(table)
    console.print()


def _render_list_summary(ctx: RenderContext, count: int, page: int | None = None) -> None:
    parts = [f"{count} result{'s' if count != 1 else ''}"]
    if page is not None:
        parts.append(f"page {page}")
    scope_parts = [f"{k}={v}" for k, v in ctx.non_null_scope().items()]
    if scope_parts:
        parts.append(", ".join(scope_parts))
    parts.append(f"{ctx.elapsed_s():.2f}s")
    console.print(f"  [{DIM_COLOR}]{' · '.join(parts)}[/]")
    console.print()


def _render_add_items(results: list[dict]) -> None:
    if not results:
        console.print(f"  [{DIM_COLOR}]No memories extracted.[/]")
        return
    console.print()
    seen_pending_events: set[str] = set()
    for r in results:
        if r.get("status") == "PENDING":
            event_id = r.get("event_id", "")
            if event_id and event_id in seen_pending_events:
                continue
            if event_id:
                seen_pending_events.add(event_id)
            icon = f"[{ACCENT_COLOR}]{_sym('⧗', '...')}[/]"
            console.print(f"  {icon} [{DIM_COLOR}]{'Queued':<10}[/]  [white]Processing in background[/]")
            if event_id:
                console.print(f"  [{DIM_COLOR}]  event_id: {event_id}[/]")
                console.print(f"  [{DIM_COLOR}]  → Check status: mem0 event status {event_id}[/]")
            continue

        event = r.get("event", "ADD")
        memory = r.get("memory") or r.get("text") or r.get("content") or r.get("data") or ""
        mem_id = str(r.get("id") or r.get("memory_id") or "")[:8]

        mapping = {
            "ADD": (f"[{SUCCESS_COLOR}]+[/]", "Added"),
            "UPDATE": (f"[{ACCENT_COLOR}]~[/]", "Updated"),
            "DELETE": ("[red]-[/]", "Deleted"),
            "NOOP": (f"[{DIM_COLOR}]·[/]", "No change"),
        }
        icon, label = mapping.get(event, (f"[{DIM_COLOR}]?[/]", event))
        parts = [f"  {icon} [{DIM_COLOR}]{label:<10}[/]"]
        if memory:
            parts.append(f"[white]{memory}[/]")
        if mem_id:
            parts.append(f"[{DIM_COLOR}]({mem_id})[/]")
        console.print("  ".join(parts))
    console.print()

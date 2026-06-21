"""Agent mode state — set by the root callback, read by commands and branding."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_agent_mode: bool = False
_current_command: str = ""
_pending_notice: str = ""
_traces: list["TraceStep"] = []
_trace_enabled: bool = True
_trace_event_id: str = ""
_trace_contract: dict[str, Any] | None = None


def _load_trace_contract() -> dict[str, Any]:
    global _trace_contract
    if _trace_contract is None:
        contract_path = Path(__file__).parent / "contract" / "payload_contract.json"
        with open(contract_path, encoding="utf-8") as f:
            contract = json.load(f)
        _trace_contract = contract.get("traceEpilogue", {})
    return _trace_contract


@dataclass
class TraceStep:
    """A single trace step captured during command execution."""

    label: str
    duration_ms: int | None = None
    status: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    _start_time: float | None = field(default=None, repr=False, compare=False)

    def start(self) -> None:
        """Start timing this step."""
        self._start_time = time.perf_counter()

    def finish(self, status: str | None = None) -> None:
        """Finish timing this step and calculate duration."""
        if self._start_time is not None:
            self.duration_ms = int((time.perf_counter() - self._start_time) * 1000)
        if status is not None:
            self.status = status


def is_agent_mode() -> bool:
    return _agent_mode


def set_agent_mode(val: bool) -> None:
    global _agent_mode
    _agent_mode = val


def get_current_command() -> str:
    return _current_command


def set_current_command(name: str) -> None:
    global _current_command
    _current_command = name


def capture_notice(notice: str | None) -> None:
    """Stash a Mem0 backend notice for end-of-command surfacing.

    Called from the platform backend after each response so the notice can
    be printed once per command (regardless of how many sub-requests fired).
    Last-write-wins is fine — the message text is identical across requests.
    """
    global _pending_notice
    if notice:
        _pending_notice = notice


def take_notice() -> str:
    """Return and clear the pending notice."""
    global _pending_notice
    msg = _pending_notice
    _pending_notice = ""
    return msg


# ---------------------------------------------------------------------------
# Trace epilogue
# ---------------------------------------------------------------------------

def set_trace_enabled(enabled: bool) -> None:
    """Enable or disable trace collection."""
    global _trace_enabled
    _trace_enabled = enabled


def is_trace_enabled() -> bool:
    """Return True if trace collection is enabled."""
    return _trace_enabled and not is_agent_mode()


def set_trace_event_id(event_id: str) -> None:
    """Set the event ID for the current command's trace."""
    global _trace_event_id
    _trace_event_id = event_id


def get_trace_event_id() -> str:
    """Get the event ID for the current command's trace."""
    return _trace_event_id


def add_trace_step(label: str, *, start: bool = False) -> TraceStep:
    """Add a new trace step and optionally start timing it.

    Returns the TraceStep instance so caller can call .finish() on it.
    """
    step = TraceStep(label=label)
    if start and is_trace_enabled():
        step.start()
    if is_trace_enabled():
        _traces.append(step)
    return step


def get_trace_steps() -> list[TraceStep]:
    """Return all collected trace steps."""
    return list(_traces)


def clear_trace_steps() -> None:
    """Clear all collected trace steps (called at end of command)."""
    global _traces, _trace_event_id
    _traces = []
    _trace_event_id = ""


def format_trace_epilogue() -> str | None:
    """Format the collected trace steps as a trace epilogue table.

    Returns None if tracing is disabled or no steps were collected.
    """
    from mem0_cli.branding import ACCENT_COLOR, DIM_COLOR

    if not is_trace_enabled():
        return None

    contract = _load_trace_contract()
    steps = get_trace_steps()

    if not steps:
        return None

    min_duration = contract.get("minDurationMs", 5)
    filtered = [s for s in steps if s.duration_ms is None or s.duration_ms >= min_duration]

    if not filtered:
        return None

    header_label = contract.get("headerLabel", "STEP")
    header_duration = contract.get("headerDuration", "DURATION")
    header_status = contract.get("headerStatus", "STATUS")

    label_width = contract.get("labelWidth", 18)
    duration_width = contract.get("durationWidth", 10)
    status_width = contract.get("statusWidth", 10)

    status_colors = contract.get("statusColors", {
        "success": "green",
        "failed": "red",
        "skipped": "yellow",
        "pending": "dim",
    })
    default_status = contract.get("defaultStatus", "success")

    from rich.table import Table
    from rich.text import Text

    table = Table(
        show_header=True,
        header_style=ACCENT_COLOR,
        show_edge=False,
        show_lines=False,
        padding=0,
    )
    table.add_column(header_label, width=label_width, style=DIM_COLOR)
    table.add_column(header_duration, width=duration_width, justify="right")
    table.add_column(header_status, width=status_width, justify="right")

    total_ms = 0
    for step in filtered:
        status = step.status or default_status
        color_map = {
            "green": "green",
            "red": "red",
            "yellow": "yellow",
            "dim": DIM_COLOR,
            "success": "green",
            "failed": "red",
            "skipped": "yellow",
            "pending": DIM_COLOR,
        }
        status_style = color_map.get(status_colors.get(status, ""), DIM_COLOR)

        if step.duration_ms is not None:
            duration_str = f"{step.duration_ms:>6} ms"
            total_ms += step.duration_ms
        else:
            duration_str = "     —"

        status_text = Text(status.upper(), style=status_style)
        table.add_row(f"  {step.label}", duration_str, status_text)

    total_label = contract.get("totalLabel", "Total")
    table.add_row(
        f"  [{ACCENT_COLOR}]{total_label}[/{ACCENT_COLOR}]",
        f"[{ACCENT_COLOR}]{total_ms:>6} ms[/{ACCENT_COLOR}]",
        "",
    )

    from rich.console import Console
    import io

    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False)
    console.print(table)

    trace_event_id = get_trace_event_id()
    if trace_event_id:
        trace_command = contract.get("traceCommand", "mem0 trace {event_id}")
        trace_command = trace_command.replace("{event_id}", trace_event_id)
        buf.write(f"\n  [{DIM_COLOR}]  For full trace: {trace_command}[/{DIM_COLOR}]\n")

    return buf.getvalue()


def emit_trace_epilogue(console) -> None:
    """Emit the trace epilogue to the given console if enabled."""
    epilogue = format_trace_epilogue()
    if epilogue:
        console.print(epilogue)

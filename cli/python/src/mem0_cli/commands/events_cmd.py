"""Background event inspection commands — driven by registry descriptors."""

from __future__ import annotations

from mem0_cli.core.descriptors import EVENT_LIST, EVENT_STATUS
from mem0_cli.core.options import require_positive
from mem0_cli.core.registry import run_command


def cmd_event_list(
    backend,
    *,
    config=None,
    page: int = 1,
    page_size: int = 20,
    output: str = "table",
) -> None:
    require_positive(page, field="--page")
    require_positive(page_size, field="--page-size")
    run_command(
        EVENT_LIST,
        backend=backend,
        config=config,
        output=output,
        payload_kwargs={"page": page, "page_size": page_size},
    )


def cmd_event_status(
    backend,
    event_id: str,
    *,
    config=None,
    output: str = "text",
) -> None:
    run_command(
        EVENT_STATUS,
        backend=backend,
        config=config,
        output=output,
        payload_kwargs={"event_id": event_id},
    )

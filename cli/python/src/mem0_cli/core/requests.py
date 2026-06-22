"""Backend request builders.

These modules take *parsed, validated* options (from :mod:`options`) and
return exactly the kwargs that :class:`mem0_cli.backend.base.Backend`
methods expect.

This keeps the CLI command layer completely agnostic about backend
parameter naming conventions and also lets us test option → payload
translation independently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mem0_cli.core.errors import InputError
from mem0_cli.core.options import (
    parse_categories,
    parse_expires,
    parse_fields,
    parse_filter_json,
    parse_metadata,
    read_messages_from_file,
    read_stdin,
    require_one,
)

# ── Memory: add ───────────────────────────────────────────────────────────


def build_add_payload(
    *,
    text: str | None,
    messages: str | None,
    file: Path | None,
    metadata: str | None,
    immutable: bool,
    no_infer: bool,
    expires: str | None,
    categories: str | None,
    scope: dict[str, str | None],
) -> dict[str, Any]:
    """Build kwargs for ``Backend.add()`` from CLI option values.

    Raises :class:`InputError` when no content source is provided.
    """

    msgs = None
    content = text

    if file:
        msgs = read_messages_from_file(file)
    elif messages:
        try:
            import json as _json

            msgs = _json.loads(messages)
        except Exception as exc:
            raise InputError(f"Invalid JSON in --messages: {exc}") from None
    elif not content:
        content = read_stdin()

    require_one(
        content,
        msgs,
        message="No content provided. Pass text, --messages, --file, or pipe via stdin.",
    )

    return {
        "content": content,
        "messages": msgs,
        "metadata": parse_metadata(metadata),
        "immutable": bool(immutable),
        "infer": not no_infer,
        "expires": parse_expires(expires),
        "categories": parse_categories(categories),
        **scope,
    }


# ── Memory: search ────────────────────────────────────────────────────────


def build_search_payload(
    *,
    query: str,
    top_k: int,
    threshold: float,
    rerank: bool,
    keyword: bool,
    filter_json: str | None,
    fields: str | None,
    scope: dict[str, str | None],
) -> dict[str, Any]:
    """Build kwargs for ``Backend.search()``."""

    return {
        "query": query,
        "top_k": int(top_k),
        "threshold": float(threshold),
        "rerank": bool(rerank),
        "keyword": bool(keyword),
        "filters": parse_filter_json(filter_json),
        "fields": parse_fields(fields),
        **scope,
    }


# ── Memory: list ──────────────────────────────────────────────────────────


def build_list_payload(
    *,
    page: int,
    page_size: int,
    category: str | None,
    after: str | None,
    before: str | None,
    scope: dict[str, str | None],
) -> dict[str, Any]:
    """Build kwargs for ``Backend.list_memories()``."""

    return {
        "page": int(page),
        "page_size": int(page_size),
        "category": category,
        "after": after,
        "before": before,
        **scope,
    }


# ── Memory: update ────────────────────────────────────────────────────────


def build_update_payload(
    *,
    memory_id: str,
    text: str | None,
    metadata: str | None,
) -> dict[str, Any]:
    """Build kwargs for ``Backend.update()``."""

    return {
        "memory_id": memory_id,
        "content": text or read_stdin(),
        "metadata": parse_metadata(metadata),
    }


# ── Memory: delete (single) ──────────────────────────────────────────────


def build_delete_payload(
    *,
    memory_id: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"memory_id": memory_id}
    if dry_run:
        payload["dry_run"] = True
    return payload


# ── Memory: delete all ────────────────────────────────────────────────────


def build_delete_all_payload(
    *,
    all_project: bool = False,
    all_: bool = False,
    scope: dict[str, str | None],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Build kwargs for ``Backend.delete(all=True)``.

    When *all_project* (or the legacy *all_*) is True the entity IDs are set
    to ``"*"`` so the backend wipes the whole project.
    """

    project_wide = all_project or all_
    payload: dict[str, Any] = {"all": True}
    if dry_run:
        payload["dry_run"] = True
    if project_wide:
        payload.update(user_id="*", agent_id="*", app_id="*", run_id="*")
    else:
        payload.update(scope)
    return payload


# ── Entity delete ─────────────────────────────────────────────────────────


def build_entity_delete_payload(
    *,
    scope: dict[str, str | None],
) -> dict[str, Any]:
    """Build kwargs for ``Backend.delete_entities()``."""

    if not any(scope.values()):
        raise InputError(
            "Provide at least one of --user-id, --agent-id, --app-id, --run-id."
        )
    return scope


# ── Import ────────────────────────────────────────────────────────────────


def iter_import_items(
    file_path: str,
    *,
    user_id: str | None,
    agent_id: str | None,
) -> tuple[list[dict], int]:
    """Load import file and yield ``(backend_kwargs_list, total)``.

    Loads everything into memory up-front so we can show a progress bar.
    Items without a memory/text/content are pre-filtered and counted in
    the returned *total* for accurate progress reporting.
    """

    try:
        import json as _json

        raw = Path(file_path).read_text()
        data = _json.loads(raw)
    except FileNotFoundError:
        raise InputError(f"File not found: {file_path}") from None
    except Exception as exc:
        raise InputError(f"Failed to read file '{file_path}': {exc}") from None

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise InputError("Import file must contain a JSON array or object.")

    items: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        content = item.get("memory", item.get("text", item.get("content", "")))
        if not content:
            continue
        items.append(
            {
                "content": content,
                "user_id": user_id or item.get("user_id"),
                "agent_id": agent_id or item.get("agent_id"),
                "metadata": item.get("metadata"),
            }
        )
    return items, len(data)

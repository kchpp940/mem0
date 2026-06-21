"""Reusable CLI option builders derived from the shared CLI contract.

This module centralizes option definitions, validation rules, and default values
so that every command uses consistent parameter names, help text, and defaults.

All option builders follow the contract defined in ``cli/cli-spec.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mem0.schema.fields import FIELD_VALIDATION

CONTRACT_PATH = Path(__file__).parent / "contract" / "payload_contract.json"


def _load_contract() -> dict[str, Any]:
    with open(CONTRACT_PATH) as f:
        return json.load(f)


_contract = _load_contract()
_defaults: dict[str, Any] = _contract.get("defaults", {})


def scope_options(
    *,
    help_panel: str = "Scope",
) -> dict[str, Any]:
    """Return Typer option kwargs for the standard scope option group.

    Returns a dict of keyword arguments suitable for ``typer.Option()`` calls.
    Each key is the snake_case option name; each value is a dict of
    ``{"default": ..., "param_decls": [...], "help": ..., "rich_help_panel": ...}``.
    """
    return {
        "user_id": {
            "default": None,
            "param_decls": ["--user-id", "-u"],
            "help": "Scope to user.",
            "rich_help_panel": help_panel,
        },
        "agent_id": {
            "default": None,
            "param_decls": ["--agent-id"],
            "help": "Scope to agent.",
            "rich_help_panel": help_panel,
        },
        "app_id": {
            "default": None,
            "param_decls": ["--app-id"],
            "help": "Scope to app.",
            "rich_help_panel": help_panel,
        },
        "run_id": {
            "default": None,
            "param_decls": ["--run-id"],
            "help": "Scope to run.",
            "rich_help_panel": help_panel,
        },
    }


def output_option(
    *,
    default: str = "text",
    choices: list[str] | None = None,
    help_panel: str = "Output",
) -> dict[str, Any]:
    """Return Typer option kwargs for the standard --output option."""
    choices_str = ", ".join(choices) if choices else "text, json, table, quiet"
    return {
        "default": default,
        "param_decls": ["--output", "-o"],
        "help": f"Output format: {choices_str}.",
        "rich_help_panel": help_panel,
    }


def connection_options(
    *,
    help_panel: str = "Connection",
) -> dict[str, Any]:
    """Return Typer option kwargs for the standard connection option group."""
    return {
        "api_key": {
            "default": None,
            "param_decls": ["--api-key"],
            "help": "Override API key.",
            "rich_help_panel": help_panel,
            "envvar": "MEM0_API_KEY",
        },
        "base_url": {
            "default": None,
            "param_decls": ["--base-url"],
            "help": "Override API base URL.",
            "rich_help_panel": help_panel,
        },
    }


def search_options(
    *,
    help_panel: str = "Search",
) -> dict[str, Any]:
    """Return Typer option kwargs for the standard search option group."""
    return {
        "top_k": {
            "default": _defaults.get("top_k", 10),
            "param_decls": ["--top-k", "-k", "--limit"],
            "help": "Number of results.",
            "rich_help_panel": help_panel,
        },
        "threshold": {
            "default": _defaults.get("threshold", 0.3),
            "param_decls": ["--threshold"],
            "help": "Minimum similarity score.",
            "rich_help_panel": help_panel,
        },
        "rerank": {
            "default": _defaults.get("rerank", False),
            "param_decls": ["--rerank"],
            "help": "Enable reranking (Platform only).",
            "rich_help_panel": help_panel,
        },
        "keyword": {
            "default": _defaults.get("keyword", False),
            "param_decls": ["--keyword"],
            "help": "Use keyword search.",
            "rich_help_panel": help_panel,
        },
        "filter_json": {
            "default": None,
            "param_decls": ["--filter"],
            "help": "Advanced filter expression (JSON).",
            "rich_help_panel": help_panel,
        },
        "fields": {
            "default": None,
            "param_decls": ["--fields"],
            "help": "Specific fields to return (comma-separated).",
            "rich_help_panel": help_panel,
        },
    }


def pagination_options(
    *,
    help_panel: str = "Pagination",
) -> dict[str, Any]:
    """Return Typer option kwargs for the standard pagination option group."""
    return {
        "page": {
            "default": 1,
            "param_decls": ["--page"],
            "help": "Page number.",
            "rich_help_panel": help_panel,
        },
        "page_size": {
            "default": 100,
            "param_decls": ["--page-size"],
            "help": "Results per page.",
            "rich_help_panel": help_panel,
        },
    }


def filter_options(
    *,
    help_panel: str = "Filters",
) -> dict[str, Any]:
    """Return Typer option kwargs for the standard filter option group."""
    return {
        "category": {
            "default": None,
            "param_decls": ["--category"],
            "help": "Filter by category.",
            "rich_help_panel": help_panel,
        },
        "after": {
            "default": None,
            "param_decls": ["--after"],
            "help": "Created after (YYYY-MM-DD).",
            "rich_help_panel": help_panel,
        },
        "before": {
            "default": None,
            "param_decls": ["--before"],
            "help": "Created before (YYYY-MM-DD).",
            "rich_help_panel": help_panel,
        },
    }


def add_options() -> dict[str, Any]:
    """Return Typer option kwargs for the standard add command options."""
    return {
        "messages": {
            "default": None,
            "param_decls": ["--messages"],
            "help": "Conversation messages as JSON.",
        },
        "file": {
            "default": None,
            "param_decls": ["--file", "-f"],
            "help": "Read messages from JSON file.",
        },
        "metadata": {
            "default": None,
            "param_decls": ["--metadata", "-m"],
            "help": "Custom metadata as JSON.",
        },
        "immutable": {
            "default": _defaults.get("immutable", False),
            "param_decls": ["--immutable"],
            "help": "Prevent future updates.",
        },
        "no_infer": {
            "default": False,
            "param_decls": ["--no-infer"],
            "help": "Skip inference, store raw.",
        },
        "expires": {
            "default": None,
            "param_decls": ["--expires"],
            "help": "Expiration date (YYYY-MM-DD).",
        },
        "categories": {
            "default": None,
            "param_decls": ["--categories"],
            "help": "Categories (JSON array or comma-separated).",
        },
    }


def validate_top_k(top_k: int) -> None:
    """Validate top_k against the contract rules."""
    if top_k < 1:
        raise ValueError(FIELD_VALIDATION["top_k"]["error"])


def validate_threshold(threshold: float) -> None:
    """Validate threshold against the contract rules."""
    if not (0.0 <= threshold <= 1.0):
        raise ValueError(FIELD_VALIDATION["threshold"]["error"])


def validate_page(page: int) -> None:
    """Validate page number against the contract rules."""
    if page < 1:
        raise ValueError(FIELD_VALIDATION["page"]["error"])


def validate_page_size(page_size: int) -> None:
    """Validate page size against the contract rules."""
    if page_size < 1:
        raise ValueError(FIELD_VALIDATION["page_size"]["error"])


def parse_json_option(value: str | None, *, name: str) -> Any:
    """Parse a JSON-encoded CLI option, raising a ValueError on failure.

    Parameters
    ----------
    value:
        Raw string from the CLI, or ``None`` if not provided.
    name:
        Option name used in error messages (e.g. ``"--filter"``).
    """
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {name}: {e}") from None


def parse_categories(value: str | None) -> list[str] | None:
    """Parse --categories: try JSON array first, fall back to comma-split."""
    if value is None:
        return None
    try:
        parsed = json.loads(value)
        if not isinstance(parsed, list):
            raise ValueError("--categories JSON must be an array.")
        return [str(x) for x in parsed]
    except json.JSONDecodeError:
        return [c.strip() for c in value.split(",")]


def parse_fields(value: str | None) -> list[str] | None:
    """Parse --fields: comma-separated list."""
    if value is None:
        return None
    return [f.strip() for f in value.split(",")]


def build_scope(
    *,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, str] | None:
    """Build a scope dict from entity IDs, returning None if all are empty.

    The scope dict only includes keys with non-None values, matching the
    JSON envelope contract.
    """
    scope: dict[str, str] = {}
    if user_id:
        scope["user_id"] = user_id
    if agent_id:
        scope["agent_id"] = agent_id
    if app_id:
        scope["app_id"] = app_id
    if run_id:
        scope["run_id"] = run_id
    return scope or None

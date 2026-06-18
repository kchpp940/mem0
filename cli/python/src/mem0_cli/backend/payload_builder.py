"""Shared payload builder for Platform API requests.

Centralizes parameter normalization, validation, filter building, and payload
construction for add/search/list operations so Python and Node CLIs produce
identical request payloads with consistent error messages.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from mem0_cli.branding import print_error


@dataclass
class ValidationError(Exception):
    """Raised when parameter validation fails."""

    message: str


def normalize_categories(raw: str | None) -> list[str] | None:
    """Parse categories from CLI input (JSON array or comma-separated string).

    Args:
        raw: Raw categories string from CLI (e.g. '["work","personal"]' or 'work,personal')

    Returns:
        List of category strings, or None if raw is None/empty.

    Raises:
        ValidationError: If JSON is provided but invalid.
    """
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValidationError("--categories JSON must be an array.")
        return [str(c).strip() for c in parsed if c]
    except json.JSONDecodeError:
        return [c.strip() for c in raw.split(",") if c.strip()]


def validate_expires(raw: str | None) -> str | None:
    """Validate expires date format and ensure it's in the future.

    Args:
        raw: Raw expires string from CLI (expected: YYYY-MM-DD)

    Returns:
        Validated date string if provided.

    Raises:
        ValidationError: If format is invalid or date is not in the future.
    """
    if not raw:
        return None
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        raise ValidationError(
            "Invalid date format for --expires. Use YYYY-MM-DD (e.g. 2025-12-31)."
        )
    if date.fromisoformat(raw) <= date.today():
        raise ValidationError("--expires date must be in the future.")
    return raw


def parse_filter_json(raw: str | None) -> dict | None:
    """Parse JSON filter string from CLI.

    Args:
        raw: Raw JSON filter string from --filter flag.

    Returns:
        Parsed filter dict, or None if raw is None.

    Raises:
        ValidationError: If JSON is invalid.
    """
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValidationError("--filter must be a JSON object.")
        return parsed
    except json.JSONDecodeError as e:
        raise ValidationError(f"Invalid JSON in --filter: {e}") from None


def build_filters(
    *,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    extra_filters: dict | None = None,
) -> dict | None:
    """Build a filters dict for v3 Platform API endpoints.

    Entity IDs are ANDed (all provided IDs must match). Extra filters (date
    ranges, categories) are also ANDed. If caller passes a pre-built filter
    structure (e.g. with AND/OR keys), it is returned as-is.

    Args:
        user_id: User ID filter.
        agent_id: Agent ID filter.
        app_id: App ID filter.
        run_id: Run ID filter.
        extra_filters: Additional filters to merge (e.g. from --filter flag).

    Returns:
        Filter structure ready for API payload, or None if no filters.
    """
    # If caller passed a pre-built filter structure, use it directly
    if extra_filters and ("AND" in extra_filters or "OR" in extra_filters):
        return extra_filters

    and_conditions: list[dict[str, Any]] = []
    if user_id:
        and_conditions.append({"user_id": user_id})
    if agent_id:
        and_conditions.append({"agent_id": agent_id})
    if app_id:
        and_conditions.append({"app_id": app_id})
    if run_id:
        and_conditions.append({"run_id": run_id})

    if extra_filters:
        for k, v in extra_filters.items():
            and_conditions.append({k: v})

    if len(and_conditions) == 1:
        return and_conditions[0]
    elif and_conditions:
        return {"AND": and_conditions}
    return None


def build_add_payload(
    *,
    content: str | None = None,
    messages: list[dict] | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    metadata: dict | None = None,
    immutable: bool = False,
    infer: bool = True,
    expires: str | None = None,
    categories: list[str] | None = None,
) -> dict[str, Any]:
    """Build payload for POST /v3/memories/add/.

    Args:
        content: Raw text content (wrapped in user message if no messages).
        messages: Pre-constructed message array (takes precedence over content).
        user_id: User ID to attach.
        agent_id: Agent ID to attach.
        app_id: App ID to attach.
        run_id: Run ID to attach.
        metadata: Metadata dict.
        immutable: Whether memory is immutable.
        infer: Whether to enable inference.
        expires: Validated expiration date (YYYY-MM-DD).
        categories: List of categories.

    Returns:
        Complete add payload ready for the API.
    """
    payload: dict[str, Any] = {}

    if messages:
        payload["messages"] = messages
    elif content:
        payload["messages"] = [{"role": "user", "content": content}]

    if user_id:
        payload["user_id"] = user_id
    if agent_id:
        payload["agent_id"] = agent_id
    if app_id:
        payload["app_id"] = app_id
    if run_id:
        payload["run_id"] = run_id
    if metadata:
        payload["metadata"] = metadata
    if immutable:
        payload["immutable"] = True
    if not infer:
        payload["infer"] = False
    if expires:
        payload["expiration_date"] = expires
    if categories:
        payload["categories"] = categories
    payload["source"] = "CLI"

    return payload


def build_search_payload(
    query: str,
    *,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    top_k: int = 10,
    threshold: float = 0.3,
    rerank: bool = False,
    keyword: bool = False,
    filters: dict | None = None,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """Build payload for POST /v3/memories/search/.

    Args:
        query: Search query string.
        user_id: User ID filter.
        agent_id: Agent ID filter.
        app_id: App ID filter.
        run_id: Run ID filter.
        top_k: Number of results to return.
        threshold: Minimum similarity threshold.
        rerank: Whether to enable reranking.
        keyword: Whether to use keyword search.
        filters: Pre-built filters dict (from build_filters()).
        fields: List of fields to return.

    Returns:
        Complete search payload ready for the API.
    """
    payload: dict[str, Any] = {"query": query, "top_k": top_k, "threshold": threshold}

    api_filters = build_filters(
        user_id=user_id,
        agent_id=agent_id,
        app_id=app_id,
        run_id=run_id,
        extra_filters=filters,
    )
    if api_filters:
        payload["filters"] = api_filters
    if rerank:
        payload["rerank"] = True
    if keyword:
        payload["keyword_search"] = True
    if fields:
        payload["fields"] = fields
    payload["source"] = "CLI"

    return payload


def build_list_payload(
    *,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    category: str | None = None,
    after: str | None = None,
    before: str | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build payload and query params for POST /v3/memories/.

    Args:
        user_id: User ID filter.
        agent_id: Agent ID filter.
        app_id: App ID filter.
        run_id: Run ID filter.
        category: Category filter (contains match).
        after: Created-at lower bound (ISO date).
        before: Created-at upper bound (ISO date).

    Returns:
        Tuple of (payload dict, query params dict).
    """
    payload: dict[str, Any] = {}
    params: dict[str, str] = {}

    extra: dict[str, Any] = {}
    if category:
        extra["categories"] = {"contains": category}
    if after:
        extra["created_at"] = {**(extra.get("created_at", {})), "gte": after}
    if before:
        extra["created_at"] = {**(extra.get("created_at", {})), "lte": before}

    api_filters = build_filters(
        user_id=user_id,
        agent_id=agent_id,
        app_id=app_id,
        run_id=run_id,
        extra_filters=extra if extra else None,
    )
    if api_filters:
        payload["filters"] = api_filters
    payload["source"] = "CLI"

    return payload, params


def handle_validation_error(err: ValidationError, err_console: Any) -> None:
    """Print a validation error to stderr and exit.

    This provides a single exit point for validation errors so both CLIs show
    the same error formatting.

    Args:
        err: The ValidationError to handle.
        err_console: Rich console for stderr output.
    """
    print_error(err_console, err.message)
    raise SystemExit(1) from None

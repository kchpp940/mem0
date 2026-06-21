"""API response normalization helpers.

This module normalizes inconsistent API response shapes into a canonical
form used by the output renderer and downstream code.

Normalization rules follow the shared CLI contract in ``cli/cli-spec.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONTRACT_PATH = Path(__file__).parent / "contract" / "payload_contract.json"


def _load_contract() -> dict[str, Any]:
    with open(CONTRACT_PATH) as f:
        return json.load(f)


_contract = _load_contract()
_mapping: dict[str, Any] = _contract.get("fieldMapping", {})
_search_keys: list[str] = _contract.get("searchListKeys", ["results", "memories"])
_add_result_key: str = _contract.get("addResultKey", "results")
_pending_config: dict[str, Any] = _contract.get("pendingDedup", {})


def pick_fields(data: dict[str, Any], fields: list[str] | None) -> dict[str, Any]:
    """Return a new dict containing only the requested fields.

    If ``fields`` is ``None`` or empty, return the original dict unchanged.
    """
    if not fields:
        return data
    return {k: v for k, v in data.items() if k in fields}


def extract_list(data: Any) -> list[Any]:
    """Extract a list of items from a response that may wrap them in keys like
    ``results`` or ``memories``.

    Follows the contract's ``searchListKeys`` preference order.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in _search_keys:
            if key in data and isinstance(data[key], list):
                return data[key]
    return []


def extract_add_results(data: Any) -> list[Any]:
    """Extract the results array from an add-memory response.

    The Platform API returns ``{"results": [...]}`` while OSS may return
    the list directly or ``{"results": [...]}``.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        results = data.get(_add_result_key)
        if isinstance(results, list):
            return results
    return []


def dedup_pending(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate PENDING events by the configured dedup key.

    This handles the case where the API returns both a synchronous PENDING
    event and the same event again from an async trace.  Only events with
    status equal to the pending value are deduplicated.
    """
    status_key = _pending_config.get("statusKey", "status")
    pending_value = _pending_config.get("pendingValue", "PENDING")
    dedup_key = _pending_config.get("dedupKey", "event_id")

    seen_ids: set[str] = set()
    result: list[dict[str, Any]] = []

    for item in results:
        if not isinstance(item, dict):
            result.append(item)
            continue
        status = item.get(status_key)
        if status == pending_value:
            event_id = item.get(dedup_key)
            if event_id is not None:
                if event_id in seen_ids:
                    continue
                seen_ids.add(event_id)
        result.append(item)

    return result


def build_filters(
    *,
    entity_ids: dict[str, str | None] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build a filters dict from entity IDs and extra filter options.

    Parameters
    ----------
    entity_ids:
        Mapping of entity field names (``user_id``, ``agent_id``, etc.) to
        their values.  Only non-``None`` values are included.
    extra:
        Additional filter conditions (e.g. from ``--category``, ``--after``).

    Returns
    -------
    dict or None
        Combined filter dict, or ``None`` if no filters were provided.
    """
    entity_ids = entity_ids or {}
    extra = extra or {}

    filters: dict[str, Any] = {}

    filter_building = _contract.get("filterBuilding", {})
    entity_order = filter_building.get(
        "entityOrder", ["user_id", "agent_id", "app_id", "run_id"]
    )
    combine_op = filter_building.get("combineOperator", "AND")

    for field in entity_order:
        value = entity_ids.get(field)
        if value is not None:
            filters[field] = value

    list_extra = filter_building.get("listExtra", {})
    for key, config in list_extra.items():
        if key in extra and extra[key] is not None:
            field = config.get("field", key)
            op = config.get("op", "eq")
            if op == "eq":
                filters[field] = extra[key]
            else:
                filters[field] = {op: extra[key]}

    if extra.get("filter") is not None:
        user_filter = extra["filter"]
        if filters:
            combined = {combine_op: [filters, user_filter]}
            return combined
        return user_filter

    return filters or None


def normalize_memory(memory: dict[str, Any]) -> dict[str, Any]:
    """Normalize a single memory dict to the canonical field names.

    Maps API field names to the CLI's canonical names using the contract's
    ``fieldMapping`` table.
    """
    if not isinstance(memory, dict):
        return memory

    result = dict(memory)
    for canon_name, api_name in _mapping.items():
        if canon_name not in result and api_name in result:
            result[canon_name] = result[api_name]

    return result


def normalize_memory_list(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize a list of memory dicts."""
    return [normalize_memory(m) for m in memories]


def has_pending(results: list[dict[str, Any]]) -> bool:
    """Return True if any result has status == PENDING."""
    status_key = _pending_config.get("statusKey", "status")
    pending_value = _pending_config.get("pendingValue", "PENDING")
    return any(
        isinstance(r, dict) and r.get(status_key) == pending_value for r in results
    )


def count_by_status(results: list[dict[str, Any]]) -> dict[str, int]:
    """Count results by their status value.

    Returns a dict mapping status string → count.  Results without a status
    field are counted under the empty string key.
    """
    status_key = _pending_config.get("statusKey", "status")
    counts: dict[str, int] = {}
    for item in results:
        if isinstance(item, dict):
            status = str(item.get(status_key, ""))
            counts[status] = counts.get(status, 0) + 1
    return counts

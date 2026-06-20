"""Unified memory response formatting utilities.

This module replaces the repeated `promoted_payload_keys` + `core_and_promoted_keys`
pattern that was duplicated 7 times across mem0/memory/main.py.

All memory response formatting MUST go through these functions to ensure
consistent field ordering, promoted-key handling, and metadata bundling.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from mem0.schema.fields import (
    CORE_AND_PROMOTED_KEY_SET,
    MEMORY_RESPONSE_FIELDS,
    PROMOTED_PAYLOAD_KEY_SET,
    PAYLOAD_TO_RESPONSE_MAP,
)


def format_memory_item(
    memory_id: str,
    payload: Dict[str, Any],
    *,
    score: Optional[float] = None,
    score_details: Optional[Dict[str, Any]] = None,
    include_score: bool = False,
) -> Dict[str, Any]:
    """Format a single memory item from vector store payload to API response format.

    This is the canonical formatter for memory responses.  It replaces the
    hand-rolled ``promoted_payload_keys`` / ``core_and_promoted_keys`` pattern
    that was previously duplicated across the codebase.

    Args:
        memory_id: The ID of the memory (vector id).
        payload: The raw payload dict from the vector store.
        score: Optional similarity score (for search results).
        score_details: Optional detailed score breakdown (when explain=True).
        include_score: Whether to include the score field in the output.

    Returns:
        A dict with the canonical memory response fields in the standard order.
    """
    result: Dict[str, Any] = {"id": memory_id}

    result["memory"] = payload.get("data", "")

    for key in ("hash", "created_at", "updated_at", "expires_at", "ttl_source", "ttl_state"):
        if key in payload:
            result[key] = payload[key]

    for key in PROMOTED_PAYLOAD_KEY_SET:
        if key in payload:
            result[key] = payload[key]

    if include_score and score is not None:
        result["score"] = score
    if score_details is not None:
        result["score_details"] = score_details

    additional_metadata = {k: v for k, v in payload.items() if k not in CORE_AND_PROMOTED_KEY_SET}
    if additional_metadata:
        if "metadata" in result and isinstance(result["metadata"], dict):
            result["metadata"].update(additional_metadata)
        else:
            result["metadata"] = additional_metadata

    ordered: Dict[str, Any] = {}
    for field in MEMORY_RESPONSE_FIELDS:
        if field in result:
            ordered[field] = result[field]
    for key, value in result.items():
        if key not in ordered:
            ordered[key] = value

    return ordered


def format_memory_list(
    memories: List[Any],
    *,
    include_scores: bool = False,
    extract_id: callable = lambda m: m.id,
    extract_payload: callable = lambda m: m.payload or {},
    extract_score: callable = lambda m: getattr(m, "score", None),
) -> List[Dict[str, Any]]:
    """Format a list of memory objects from the vector store.

    Handles different vector store return formats (flat list, nested tuple, etc.)
    and applies ``format_memory_item`` to each.

    Args:
        memories: List of memory objects from a vector store query.
        include_scores: Whether to include similarity scores in the output.
        extract_id: Callable to get the ID from a memory object.
        extract_payload: Callable to get the payload dict from a memory object.
        extract_score: Callable to get the score from a memory object.

    Returns:
        List of formatted memory response dicts.
    """
    if not memories:
        return []

    first = memories[0]
    if isinstance(first, (list, tuple)):
        actual_memories = first if len(first) > 0 else []
    else:
        actual_memories = memories

    formatted = []
    for mem in actual_memories:
        mem_id = extract_id(mem)
        payload = extract_payload(mem)
        score = extract_score(mem) if include_scores else None
        formatted.append(
            format_memory_item(
                mem_id,
                payload,
                score=score,
                include_score=include_scores,
            )
        )

    return formatted


def format_history_item(history_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Format a single history entry for API response.

    Ensures consistent field ordering and type normalization (e.g. ``is_deleted``
    is always a bool).

    Args:
        history_entry: Raw history entry dict from the database.

    Returns:
        Formatted history entry dict with canonical field order.
    """
    from mem0.schema.fields import HISTORY_RESPONSE_FIELDS

    result = dict(history_entry)
    if "is_deleted" in result:
        result["is_deleted"] = bool(result["is_deleted"])

    ordered: Dict[str, Any] = {}
    for field in HISTORY_RESPONSE_FIELDS:
        if field in result:
            ordered[field] = result[field]
    for key, value in result.items():
        if key not in ordered:
            ordered[key] = value

    return ordered


def payload_to_response(payload_key: str) -> str:
    """Map a payload key to the corresponding response key.

    Convenience re-export from mem0.schema.fields for callers that only
    import from this module.

    Args:
        payload_key: The key as it appears in the vector store payload.

    Returns:
        The key as it should appear in the API response.
    """
    return PAYLOAD_TO_RESPONSE_MAP.get(payload_key, payload_key)

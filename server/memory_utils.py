from typing import Any, Dict, List, Optional


PROMOTED_KEYS = ("user_id", "agent_id", "run_id", "actor_id", "role")

INTERNAL_KEYS = frozenset({
    "data",
    "hash",
    "created_at",
    "updated_at",
    "id",
    "text_lemmatized",
    "attributed_to",
    *PROMOTED_KEYS,
})

USER_METADATA_EXCLUDE = frozenset({
    "text_lemmatized",
    "attributed_to",
})

PASSTHROUGH_KEYS = frozenset({
    "event",
    "score",
    "score_details",
})


def extract_payload(row: Any) -> Dict[str, Any]:
    return getattr(row, "payload", None) or {}


def is_memory_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    return "memory" in item or "id" in item


def format_memory_response(
    memory_item: Dict[str, Any],
    score: Optional[float] = None,
    score_details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    raw_metadata = memory_item.get("metadata")

    if isinstance(raw_metadata, dict):
        filtered_metadata = {k: v for k, v in raw_metadata.items() if k not in USER_METADATA_EXCLUDE}
    elif raw_metadata is not None:
        filtered_metadata = raw_metadata
    else:
        filtered_metadata = None

    result: Dict[str, Any] = {
        "id": memory_item.get("id"),
        "memory": memory_item.get("memory", ""),
        "hash": memory_item.get("hash"),
        "created_at": memory_item.get("created_at"),
        "updated_at": memory_item.get("updated_at"),
    }

    for key in PROMOTED_KEYS:
        if key in memory_item:
            result[key] = memory_item[key]

    if filtered_metadata:
        result["metadata"] = filtered_metadata

    if score is not None:
        result["score"] = score

    if score_details is not None:
        result["score_details"] = score_details

    for key in PASSTHROUGH_KEYS:
        if key in memory_item and key not in result:
            result[key] = memory_item[key]

    return result


def format_vector_store_row(row: Any) -> Dict[str, Any]:
    payload = extract_payload(row)
    row_id = getattr(row, "id", None)

    promoted = {}
    for key in PROMOTED_KEYS:
        if key in payload:
            promoted[key] = payload[key]

    remaining = {
        k: v
        for k, v in payload.items()
        if k not in INTERNAL_KEYS and k not in USER_METADATA_EXCLUDE
    }

    result: Dict[str, Any] = {
        "id": row_id,
        "memory": payload.get("data", ""),
        "user_id": payload.get("user_id"),
        "agent_id": payload.get("agent_id"),
        "run_id": payload.get("run_id"),
        "actor_id": promoted.get("actor_id"),
        "role": promoted.get("role"),
        "hash": payload.get("hash"),
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at"),
    }

    if remaining:
        result["metadata"] = remaining

    return result


def normalize_memory_item(item: Any) -> Any:
    if not is_memory_item(item):
        return item

    score = item.get("score") if isinstance(item, dict) else None
    score_details = item.get("score_details") if isinstance(item, dict) else None
    return format_memory_response(item, score=score, score_details=score_details)


def normalize_memory_list(items: List[Any]) -> List[Any]:
    return [normalize_memory_item(it) for it in items]


def normalize_response(response: Any) -> Any:
    if isinstance(response, dict) and "results" in response and isinstance(response["results"], list):
        return {**response, "results": normalize_memory_list(response["results"])}

    if isinstance(response, list):
        return normalize_memory_list(response)

    if is_memory_item(response):
        return normalize_memory_item(response)

    return response


def iter_formatted_rows(rows: List[Any]) -> List[Dict[str, Any]]:
    return [format_vector_store_row(row) for row in rows]


def list_vector_store_memories(
    vector_store: Any,
    limit: int = 10_000,
) -> List[Dict[str, Any]]:
    results = vector_store.list(top_k=limit)
    rows = results[0] if results and isinstance(results, list) and isinstance(results[0], list) else results or []
    return iter_formatted_rows(rows)

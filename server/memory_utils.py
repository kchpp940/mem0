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
    payload = getattr(row, "payload", None) or {}
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


def normalize_sdk_result(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return result

    if "memory" not in result and "id" not in result:
        return result

    return format_memory_response(
        result,
        score=result.get("score"),
        score_details=result.get("score_details"),
    )


def format_memory_list(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"results": [normalize_sdk_result(item) for item in items]}

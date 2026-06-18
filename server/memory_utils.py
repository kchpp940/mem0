from typing import Any, Dict, List, Literal, Optional, TypedDict

from pydantic import BaseModel


EntityType = Literal["user", "agent", "run"]
VALID_ENTITY_TYPES = frozenset({"user", "agent", "run"})


class MemoryResponseItem(TypedDict, total=False):
    id: str
    memory: str
    user_id: str
    agent_id: str
    run_id: str
    actor_id: str
    role: str
    hash: str
    metadata: Dict[str, Any]
    score: float
    score_details: Dict[str, Any]
    event: str
    created_at: str
    updated_at: str


class EntityResponseItem(TypedDict, total=False):
    id: str
    type: EntityType
    total_memories: int
    created_at: str
    updated_at: str


class MemoryListResponse(TypedDict):
    results: List[MemoryResponseItem]


class MemoryResponseModel(BaseModel):
    id: Optional[str] = None
    memory: str = ""
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    actor_id: Optional[str] = None
    role: Optional[str] = None
    hash: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    score: Optional[float] = None
    score_details: Optional[Dict[str, Any]] = None
    event: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class EntityResponseModel(BaseModel):
    id: str
    type: EntityType
    total_memories: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


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


def is_memory_response_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    return "id" in item and "memory" in item


def is_entity_response_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if "id" not in item or "type" not in item or "total_memories" not in item:
        return False
    return item["type"] in VALID_ENTITY_TYPES


def _has_list_of(items: Any, predicate) -> bool:
    if not isinstance(items, list) or not items:
        return False
    return predicate(items[0])


def format_memory_response(
    memory_item: Dict[str, Any],
    score: Optional[float] = None,
    score_details: Optional[Dict[str, Any]] = None,
) -> MemoryResponseItem:
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

    return MemoryResponseItem(**result)


def format_vector_store_row(row: Any) -> MemoryResponseItem:
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

    return MemoryResponseItem(**result)


def normalize_memory_item(item: Any) -> Any:
    if not is_memory_response_item(item):
        return item

    score = item.get("score") if isinstance(item, dict) else None
    score_details = item.get("score_details") if isinstance(item, dict) else None
    return format_memory_response(item, score=score, score_details=score_details)


def normalize_memory_list(items: List[Any]) -> List[Any]:
    return [normalize_memory_item(it) for it in items]


def normalize_response(response: Any) -> Any:
    if isinstance(response, dict) and "results" in response and isinstance(response["results"], list):
        if _has_list_of(response["results"], is_memory_response_item):
            return {**response, "results": normalize_memory_list(response["results"])}
        return response

    if isinstance(response, list):
        if _has_list_of(response, is_memory_response_item):
            return normalize_memory_list(response)
        return response

    if is_memory_response_item(response):
        return normalize_memory_item(response)

    return response


def iter_formatted_rows(rows: List[Any]) -> List[MemoryResponseItem]:
    return [format_vector_store_row(row) for row in rows]


def list_vector_store_memories(
    vector_store: Any,
    limit: int = 10_000,
) -> List[MemoryResponseItem]:
    results = vector_store.list(top_k=limit)
    rows = results[0] if results and isinstance(results, list) and isinstance(results[0], list) else results or []
    return iter_formatted_rows(rows)

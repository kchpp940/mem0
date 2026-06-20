"""Canonical field definitions for memory operations.

This module is the single source of truth (SSOT) for ALL memory-related field
definitions across the entire codebase:
- Field names used across API payload, CLI options, and SDK methods
- Name mappings between different layers (e.g. CLI camelCase → API snake_case)
- Default values for optional parameters
- Validation constraints and error messages
- Response/payload field classification (core, promoted, metadata)
- Export / import field definitions
- Feedback field definitions
- History field definitions

All consumers MUST import from this module rather than hard-coding field names,
defaults, validation messages, or response formatting logic.

TypeScript side is generated from this file via scripts/generate_ts_schema.py.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from pydantic import BaseModel, Field


# ─── Entity identifiers ───────────────────────────────────────────────────────

ENTITY_FIELDS: Tuple[str, ...] = ("user_id", "agent_id", "app_id", "run_id")
ENTITY_FIELD_SET: FrozenSet[str] = frozenset(ENTITY_FIELDS)


# ─── CLI ↔ API name mappings ─────────────────────────────────────────────────

CLI_TO_API_MAP: Dict[str, str] = {
    "userId": "user_id",
    "agentId": "agent_id",
    "appId": "app_id",
    "runId": "run_id",
    "topK": "top_k",
    "pageSize": "page_size",
    "filterJson": "filters",
    "feedbackReason": "feedback_reason",
    "memoryExportId": "memory_export_id",
    "exportInstructions": "export_instructions",
    "startDate": "start_date",
    "endDate": "end_date",
}

API_TO_CLI_MAP: Dict[str, str] = {v: k for k, v in CLI_TO_API_MAP.items()}


# ─── Default values ──────────────────────────────────────────────────────────

FIELD_DEFAULTS: Dict[str, Any] = {
    "top_k": 10,
    "threshold": 0.3,
    "page": 1,
    "page_size": 100,
    "infer": True,
    "rerank": False,
    "keyword": False,
    "immutable": False,
}


# ─── Expires validation ──────────────────────────────────────────────────────

EXPIRES_FORMAT = r"^\d{4}-\d{2}-\d{2}$"
EXPIRES_FORMAT_DISPLAY = "YYYY-MM-DD"


# ─── Field validation rules ──────────────────────────────────────────────────

FIELD_VALIDATION: Dict[str, Dict[str, Any]] = {
    "top_k": {"min": 1, "error": "--top-k must be >= 1."},
    "threshold": {"min": 0.0, "max": 1.0, "error": "--threshold must be between 0.0 and 1.0."},
    "page": {"min": 1, "error": "--page must be >= 1."},
    "page_size": {"min": 1, "error": "--page-size must be >= 1."},
}


# ─── API field aliases (where the payload key differs from the logical name) ─

ADD_API_FIELD_MAP: Dict[str, str] = {
    "expires": "expiration_date",
    "keyword": "keyword_search",
}

SEARCH_API_FIELD_MAP: Dict[str, str] = {
    "keyword": "keyword_search",
}


# ─── Scope display names (for human-readable messages) ───────────────────────

SCOPE_DISPLAY_NAMES: Dict[str, str] = {
    "user_id": "user",
    "agent_id": "agent",
    "app_id": "app",
    "run_id": "run",
}


# ─── Response / payload field classification ─────────────────────────────────
#
# Memory payloads stored in vector stores contain many keys.  When building a
# response dict, we classify them into three groups:
#
#   1. CORE_PAYLOAD_KEYS   – always present, directly mapped to response fields
#   2. PROMOTED_PAYLOAD_KEYS – lifted to top-level response fields (not nested
#                              under "metadata")
#   3. Everything else     – collected under the "metadata" key
#
# The set CORE_PAYLOAD_KEYS ∪ PROMOTED_PAYLOAD_KEYS is the set of keys that are
# NOT bundled into the "metadata" dict.

CORE_PAYLOAD_KEYS: Tuple[str, ...] = (
    "data",
    "hash",
    "created_at",
    "updated_at",
    "id",
    "text_lemmatized",
    "attributed_to",
    "expires_at",
    "ttl_source",
    "ttl_state",
)

PROMOTED_PAYLOAD_KEYS: Tuple[str, ...] = (
    "user_id",
    "agent_id",
    "run_id",
    "actor_id",
    "role",
    "categories",
    "feedback_status",
    "operation_id",
)

PROMOTED_PAYLOAD_KEY_SET: FrozenSet[str] = frozenset(PROMOTED_PAYLOAD_KEYS)

CORE_AND_PROMOTED_KEY_SET: FrozenSet[str] = frozenset({*CORE_PAYLOAD_KEYS, *PROMOTED_PAYLOAD_KEYS})


# ─── Memory response field order (canonical ordering for API responses) ──────

MEMORY_RESPONSE_FIELDS: Tuple[str, ...] = (
    "id",
    "memory",
    "hash",
    "user_id",
    "agent_id",
    "run_id",
    "actor_id",
    "role",
    "categories",
    "created_at",
    "updated_at",
    "expires_at",
    "ttl_state",
    "ttl_source",
    "score",
    "feedback_status",
    "operation_id",
    "metadata",
)


# ─── History response fields ─────────────────────────────────────────────────

HISTORY_RESPONSE_FIELDS: Tuple[str, ...] = (
    "id",
    "memory_id",
    "old_memory",
    "new_memory",
    "event",
    "created_at",
    "updated_at",
    "is_deleted",
    "actor_id",
    "role",
)


# ─── Feedback ────────────────────────────────────────────────────────────────

FEEDBACK_VALUES: Tuple[str, ...] = ("POSITIVE", "NEGATIVE", "VERY_NEGATIVE")
FEEDBACK_SET: FrozenSet[str] = frozenset(FEEDBACK_VALUES)


# ─── Export / Import ─────────────────────────────────────────────────────────

EXPORT_FIELDS: Tuple[str, ...] = ("schema", "filters", "export_instructions")

IMPORT_FIELDS: Tuple[str, ...] = ("data", "format", "mode")


# ─── Payload → response field mapping (payload key → response key) ───────────
#
# Most payload keys map directly to response keys with the same name.
# The "data" key is special — it becomes "memory" in the response.

PAYLOAD_TO_RESPONSE_MAP: Dict[str, str] = {
    "data": "memory",
}


# ─── FieldSpec model ─────────────────────────────────────────────────────────
#
# Describes a single field across all layers (API / CLI / TypeScript).


class FieldSpec(BaseModel):
    api_name: str = Field(description="Field name as it appears in the API payload (snake_case)")
    cli_name: str = Field(description="Field name as it appears in CLI options (kebab-case or camelCase)")
    ts_name: str = Field(description="Field name as it appears in TypeScript interfaces (camelCase)")
    py_type: str = Field(description="Python type annotation string")
    default: Optional[Any] = Field(default=None, description="Default value if any")
    description: str = Field(default="", description="Human-readable description")
    required: bool = Field(default=False)
    api_alias: Optional[str] = Field(default=None, description="Alternate API key when the payload key differs from api_name (e.g. expires → expiration_date)")


ENTITY_FIELD_SPECS: List[FieldSpec] = [
    FieldSpec(api_name="user_id", cli_name="user-id", ts_name="userId", py_type="Optional[str]", description="ID of the user"),
    FieldSpec(api_name="agent_id", cli_name="agent-id", ts_name="agentId", py_type="Optional[str]", description="ID of the agent"),
    FieldSpec(api_name="app_id", cli_name="app-id", ts_name="appId", py_type="Optional[str]", description="ID of the app"),
    FieldSpec(api_name="run_id", cli_name="run-id", ts_name="runId", py_type="Optional[str]", description="ID of the run"),
]

ADD_FIELD_SPECS: List[FieldSpec] = [
    *ENTITY_FIELD_SPECS,
    FieldSpec(api_name="metadata", cli_name="metadata", ts_name="metadata", py_type="Optional[Dict[str, Any]]", description="Additional metadata for the memory"),
    FieldSpec(api_name="infer", cli_name="infer", ts_name="infer", py_type="Optional[bool]", default=True, description="Whether to infer memories from the input"),
    FieldSpec(api_name="immutable", cli_name="immutable", ts_name="immutable", py_type="bool", default=False, description="Mark memory as immutable"),
    FieldSpec(api_name="expires", cli_name="expires", ts_name="expires", py_type="Optional[str]", description="Expiration date (YYYY-MM-DD)", api_alias="expiration_date"),
    FieldSpec(api_name="categories", cli_name="categories", ts_name="categories", py_type="Optional[List[str]]", description="Categories for memory classification"),
    FieldSpec(api_name="custom_categories", cli_name="custom-categories", ts_name="customCategories", py_type="Optional[List[Dict[str, Any]]]", description="Custom categories for memory classification"),
    FieldSpec(api_name="custom_instructions", cli_name="custom-instructions", ts_name="customInstructions", py_type="Optional[str]", description="Custom instructions for fact extraction"),
    FieldSpec(api_name="memory_type", cli_name="memory-type", ts_name="memoryType", py_type="Optional[str]", description="Type of memory (e.g. procedural_memory)"),
    FieldSpec(api_name="prompt", cli_name="prompt", ts_name="prompt", py_type="Optional[str]", description="Custom prompt for fact extraction"),
]

SEARCH_FIELD_SPECS: List[FieldSpec] = [
    *ENTITY_FIELD_SPECS,
    FieldSpec(api_name="filters", cli_name="filter", ts_name="filters", py_type="Optional[Dict[str, Any]]", description="Filters for the search"),
    FieldSpec(api_name="top_k", cli_name="top-k", ts_name="topK", py_type="Optional[int]", default=10, description="Number of results to return"),
    FieldSpec(api_name="threshold", cli_name="threshold", ts_name="threshold", py_type="Optional[float]", default=0.3, description="Minimum similarity score"),
    FieldSpec(api_name="rerank", cli_name="rerank", ts_name="rerank", py_type="Optional[bool]", default=False, description="Whether to rerank results"),
    FieldSpec(api_name="keyword", cli_name="keyword", ts_name="keyword", py_type="bool", default=False, description="Enable keyword search", api_alias="keyword_search"),
    FieldSpec(api_name="fields", cli_name="fields", ts_name="fields", py_type="Optional[List[str]]", description="Fields to include in response"),
    FieldSpec(api_name="categories", cli_name="categories", ts_name="categories", py_type="Optional[List[str]]", description="Categories to filter by"),
    FieldSpec(api_name="explain", cli_name="explain", ts_name="explain", py_type="Optional[bool]", default=False, description="Include score details"),
]

GET_ALL_FIELD_SPECS: List[FieldSpec] = [
    *ENTITY_FIELD_SPECS,
    FieldSpec(api_name="filters", cli_name="filter", ts_name="filters", py_type="Optional[Dict[str, Any]]", description="Filters for retrieval"),
    FieldSpec(api_name="page", cli_name="page", ts_name="page", py_type="Optional[int]", default=1, description="Page number"),
    FieldSpec(api_name="page_size", cli_name="page-size", ts_name="pageSize", py_type="Optional[int]", default=100, description="Items per page"),
    FieldSpec(api_name="categories", cli_name="categories", ts_name="categories", py_type="Optional[List[str]]", description="Categories to filter by"),
    FieldSpec(api_name="start_date", cli_name="after", ts_name="startDate", py_type="Optional[str]", description="Filter memories created on or after (ISO 8601)"),
    FieldSpec(api_name="end_date", cli_name="before", ts_name="endDate", py_type="Optional[str]", description="Filter memories created on or before (ISO 8601)"),
]

UPDATE_FIELD_SPECS: List[FieldSpec] = [
    FieldSpec(api_name="text", cli_name="text", ts_name="text", py_type="Optional[str]", description="New text content"),
    FieldSpec(api_name="metadata", cli_name="metadata", ts_name="metadata", py_type="Optional[Dict[str, Any]]", description="Updated metadata"),
    FieldSpec(api_name="timestamp", cli_name="timestamp", ts_name="timestamp", py_type="Optional[Union[int, float, str]]", description="Updated timestamp"),
]

DELETE_ALL_FIELD_SPECS: List[FieldSpec] = [
    *ENTITY_FIELD_SPECS,
]

DELETE_ENTITIES_FIELD_SPECS: List[FieldSpec] = [
    *ENTITY_FIELD_SPECS,
]


def get_add_api_key(field_name: str) -> str:
    spec = next((s for s in ADD_FIELD_SPECS if s.api_name == field_name), None)
    if spec and spec.api_alias:
        return spec.api_alias
    return ADD_API_FIELD_MAP.get(field_name, field_name)


def get_search_api_key(field_name: str) -> str:
    spec = next((s for s in SEARCH_FIELD_SPECS if s.api_name == field_name), None)
    if spec and spec.api_alias:
        return spec.api_alias
    return ADD_API_FIELD_MAP.get(field_name, field_name)


def cli_to_api(cli_name: str) -> str:
    return CLI_TO_API_MAP.get(cli_name, cli_name)


def api_to_cli(api_name: str) -> str:
    return API_TO_CLI_MAP.get(api_name, api_name)


def build_scope_dict(**entity_ids: Optional[str]) -> Dict[str, str]:
    return {k: v for k, v in entity_ids.items() if v is not None and k in ENTITY_FIELD_SET}


def build_scope_display(**entity_ids: Optional[str]) -> str:
    parts = []
    for field, value in entity_ids.items():
        if value and field in ENTITY_FIELD_SET:
            display_name = SCOPE_DISPLAY_NAMES.get(field, field)
            parts.append(f"{display_name}={value}")
    return ", ".join(parts) if parts else "ALL entities"


def validate_entity_id(value: str, field_name: str) -> str:
    if field_name not in ENTITY_FIELD_SET:
        raise ValueError(f"Unknown entity field: {field_name}")
    trimmed = value.strip()
    if not trimmed:
        raise ValueError(f"{field_name} must not be empty or whitespace-only.")
    if len(trimmed) > 255:
        raise ValueError(f"{field_name} must be at most 255 characters, got {len(trimmed)}.")
    return trimmed


def validate_expires(expires: str) -> str:
    import re
    from datetime import date

    if not re.match(EXPIRES_FORMAT, expires):
        raise ValueError(f"Invalid date format for --expires. Use {EXPIRES_FORMAT_DISPLAY} (e.g. 2025-12-31).")
    if date.fromisoformat(expires) <= date.today():
        raise ValueError("--expires date must be in the future.")
    return expires


def validate_field(name: str, value: Any) -> None:
    spec = FIELD_VALIDATION.get(name)
    if spec is None:
        return
    if "min" in spec and isinstance(value, (int, float)):
        if value < spec["min"]:
            raise ValueError(spec["error"])
    if "max" in spec and isinstance(value, (int, float)):
        if value > spec["max"]:
            raise ValueError(spec["error"])


def validate_filters_contain_entity(filters: Optional[Dict[str, Any]]) -> None:
    if not filters or not any(k in filters for k in ENTITY_FIELD_SET):
        raise ValueError(
            f"filters must contain at least one of: {', '.join(ENTITY_FIELDS[:3])}. "
            f"Example: filters={{'user_id': 'u1'}}"
        )


# ─── Feedback field specs ────────────────────────────────────────────────────

FEEDBACK_FIELD_SPECS: List[FieldSpec] = [
    FieldSpec(api_name="memory_id", cli_name="memory-id", ts_name="memoryId", py_type="str", required=True, description="ID of the memory to provide feedback for"),
    FieldSpec(api_name="feedback", cli_name="feedback", ts_name="feedback", py_type="Optional[str]", description="Feedback value (POSITIVE, NEGATIVE, VERY_NEGATIVE)"),
    FieldSpec(api_name="feedback_reason", cli_name="feedback-reason", ts_name="feedbackReason", py_type="Optional[str]", description="Reason for the feedback"),
]


# ─── Export field specs ─────────────────────────────────────────────────────

CREATE_EXPORT_FIELD_SPECS: List[FieldSpec] = [
    FieldSpec(api_name="schema", cli_name="schema", ts_name="schema", py_type="Dict[str, Any]", required=True, description="JSON schema defining the export structure"),
    FieldSpec(api_name="filters", cli_name="filter", ts_name="filters", py_type="Dict[str, Any]", required=True, description="Filters to select which memories to export"),
    FieldSpec(api_name="export_instructions", cli_name="export-instructions", ts_name="exportInstructions", py_type="Optional[str]", description="Additional instructions for the export"),
]

GET_EXPORT_FIELD_SPECS: List[FieldSpec] = [
    FieldSpec(api_name="memory_export_id", cli_name="memory-export-id", ts_name="memoryExportId", py_type="Optional[str]", description="ID of the memory export to retrieve"),
    FieldSpec(api_name="filters", cli_name="filter", ts_name="filters", py_type="Optional[Dict[str, Any]]", description="Filters to identify the export"),
]


# ─── Memory response field specs ─────────────────────────────────────────────

MEMORY_RESPONSE_FIELD_SPECS: List[FieldSpec] = [
    FieldSpec(api_name="id", cli_name="id", ts_name="id", py_type="str", required=True, description="Unique identifier of the memory"),
    FieldSpec(api_name="memory", cli_name="memory", ts_name="memory", py_type="str", required=True, description="The memory content"),
    FieldSpec(api_name="hash", cli_name="hash", ts_name="hash", py_type="Optional[str]", description="Hash of the memory content"),
    FieldSpec(api_name="user_id", cli_name="user-id", ts_name="userId", py_type="Optional[str]", description="ID of the user associated with the memory"),
    FieldSpec(api_name="agent_id", cli_name="agent-id", ts_name="agentId", py_type="Optional[str]", description="ID of the agent associated with the memory"),
    FieldSpec(api_name="run_id", cli_name="run-id", ts_name="runId", py_type="Optional[str]", description="ID of the run associated with the memory"),
    FieldSpec(api_name="actor_id", cli_name="actor-id", ts_name="actorId", py_type="Optional[str]", description="ID of the actor that created the memory"),
    FieldSpec(api_name="role", cli_name="role", ts_name="role", py_type="Optional[str]", description="Role associated with the memory"),
    FieldSpec(api_name="categories", cli_name="categories", ts_name="categories", py_type="Optional[List[str]]", description="Categories for memory classification"),
    FieldSpec(api_name="created_at", cli_name="created-at", ts_name="createdAt", py_type="Optional[str]", description="Timestamp when the memory was created"),
    FieldSpec(api_name="updated_at", cli_name="updated-at", ts_name="updatedAt", py_type="Optional[str]", description="Timestamp when the memory was last updated"),
    FieldSpec(api_name="expires_at", cli_name="expires-at", ts_name="expiresAt", py_type="Optional[str]", description="ISO 8601 timestamp when the memory expires"),
    FieldSpec(api_name="ttl_state", cli_name="ttl-state", ts_name="ttlState", py_type="Optional[str]", description="TTL lifecycle state (active, expiring_soon, expired, permanent)"),
    FieldSpec(api_name="ttl_source", cli_name="ttl-source", ts_name="ttlSource", py_type="Optional[str]", description="Which policy scope produced expires_at"),
    FieldSpec(api_name="score", cli_name="score", ts_name="score", py_type="Optional[float]", description="Similarity score (only in search results)"),
    FieldSpec(api_name="feedback_status", cli_name="feedback-status", ts_name="feedbackStatus", py_type="Optional[str]", description="Feedback status of the memory"),
    FieldSpec(api_name="operation_id", cli_name="operation-id", ts_name="operationId", py_type="Optional[str]", description="Operation ID associated with the memory"),
    FieldSpec(api_name="metadata", cli_name="metadata", ts_name="metadata", py_type="Optional[Dict[str, Any]]", description="Additional metadata"),
]


# ─── History response field specs ────────────────────────────────────────────

HISTORY_FIELD_SPECS: List[FieldSpec] = [
    FieldSpec(api_name="id", cli_name="id", ts_name="id", py_type="str", required=True, description="Unique identifier of the history entry"),
    FieldSpec(api_name="memory_id", cli_name="memory-id", ts_name="memoryId", py_type="str", required=True, description="ID of the memory this history entry belongs to"),
    FieldSpec(api_name="old_memory", cli_name="old-memory", ts_name="oldMemory", py_type="Optional[str]", description="Previous memory content"),
    FieldSpec(api_name="new_memory", cli_name="new-memory", ts_name="newMemory", py_type="Optional[str]", description="New memory content"),
    FieldSpec(api_name="event", cli_name="event", ts_name="event", py_type="str", required=True, description="Type of event (ADD, UPDATE, DELETE)"),
    FieldSpec(api_name="created_at", cli_name="created-at", ts_name="createdAt", py_type="Optional[str]", description="Timestamp when the event was created"),
    FieldSpec(api_name="updated_at", cli_name="updated-at", ts_name="updatedAt", py_type="Optional[str]", description="Timestamp when the event was last updated"),
    FieldSpec(api_name="is_deleted", cli_name="is-deleted", ts_name="isDeleted", py_type="bool", default=False, description="Whether the memory was deleted"),
    FieldSpec(api_name="actor_id", cli_name="actor-id", ts_name="actorId", py_type="Optional[str]", description="ID of the actor that performed the change"),
    FieldSpec(api_name="role", cli_name="role", ts_name="role", py_type="Optional[str]", description="Role associated with the change"),
]


# ─── Additional helper functions ─────────────────────────────────────────────

def validate_feedback_value(feedback: str) -> str:
    """Validate that a feedback value is one of the allowed values.

    Args:
        feedback: The feedback value to validate.

    Returns:
        The uppercased feedback value if valid.

    Raises:
        ValueError: If the feedback value is not valid.
    """
    upper = feedback.upper()
    if upper not in FEEDBACK_SET:
        raise ValueError(
            f"Invalid feedback value '{feedback}'. Must be one of: {', '.join(FEEDBACK_VALUES)}."
        )
    return upper


def payload_to_response_key(payload_key: str) -> str:
    """Map a payload key to the corresponding response key.

    Most keys map to themselves, but some have different names in the response
    (e.g. "data" → "memory").

    Args:
        payload_key: The key as it appears in the vector store payload.

    Returns:
        The key as it should appear in the API response.
    """
    return PAYLOAD_TO_RESPONSE_MAP.get(payload_key, payload_key)


def response_to_payload_key(response_key: str) -> str:
    """Map a response key back to the corresponding payload key.

    Args:
        response_key: The key as it appears in the API response.

    Returns:
        The key as it should appear in the vector store payload.
    """
    for payload_key, resp_key in PAYLOAD_TO_RESPONSE_MAP.items():
        if resp_key == response_key:
            return payload_key
    return response_key

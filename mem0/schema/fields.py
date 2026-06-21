"""Canonical field definitions for memory operations.

This module is the single source of truth for:
- Field names used across API payload, CLI options, and SDK methods
- Name mappings between different layers (e.g. CLI camelCase → API snake_case)
- Default values for optional parameters
- Validation constraints and error messages

All consumers (server Pydantic schemas, Python CLI, Node CLI, SDK client types)
must import from this module rather than hard-coding field names, defaults,
or validation messages.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from pydantic import BaseModel, Field


ENTITY_FIELDS: Tuple[str, ...] = ("user_id", "agent_id", "app_id", "run_id")
ENTITY_FIELD_SET: FrozenSet[str] = frozenset(ENTITY_FIELDS)

CLI_TO_API_MAP: Dict[str, str] = {
    "userId": "user_id",
    "agentId": "agent_id",
    "appId": "app_id",
    "runId": "run_id",
    "topK": "top_k",
    "pageSize": "page_size",
    "filterJson": "filters",
}

API_TO_CLI_MAP: Dict[str, str] = {v: k for k, v in CLI_TO_API_MAP.items()}

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

EXPIRES_FORMAT = r"^\d{4}-\d{2}-\d{2}$"
EXPIRES_FORMAT_DISPLAY = "YYYY-MM-DD"

FIELD_VALIDATION: Dict[str, Dict[str, Any]] = {
    "top_k": {"min": 1, "error": "--top-k must be >= 1."},
    "threshold": {"min": 0.0, "max": 1.0, "error": "--threshold must be between 0.0 and 1.0."},
    "page": {"min": 1, "error": "--page must be >= 1."},
    "page_size": {"min": 1, "error": "--page-size must be >= 1."},
}

ADD_API_FIELD_MAP: Dict[str, str] = {
    "expires": "expiration_date",
    "keyword": "keyword_search",
}

SCOPE_DISPLAY_NAMES: Dict[str, str] = {
    "user_id": "user",
    "agent_id": "agent",
    "app_id": "app",
    "run_id": "run",
}


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

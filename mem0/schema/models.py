"""Pydantic models derived from the canonical field definitions.

All Pydantic models used across server, SDK client, and CLI MUST be defined
here or derived from the field specs in mem0.schema.fields.

This is the single source of truth (SSOT) for memory-related data models.
TypeScript types are generated from these models via scripts/generate_ts_schema.py.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from mem0.schema.fields import FIELD_DEFAULTS, FEEDBACK_VALUES


# ─── Request models (for server API endpoints) ───────────────────────────────

class AddMemoryRequest(BaseModel):
    messages: List[Dict[str, str]] = Field(..., description="List of messages to store.")
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    app_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata for the memory")
    infer: Optional[bool] = Field(default=FIELD_DEFAULTS["infer"], description="Whether to extract facts from messages.")
    immutable: Optional[bool] = Field(default=False, description="Mark memory as immutable.")
    expires: Optional[str] = Field(default=None, description="Expiration date (YYYY-MM-DD).")
    categories: Optional[List[str]] = Field(default=None, description="Categories for memory classification.")
    memory_type: Optional[str] = Field(default=None, description="Type of memory (e.g. procedural_memory).")
    prompt: Optional[str] = Field(default=None, description="Custom prompt for fact extraction.")
    custom_categories: Optional[List[Dict[str, Any]]] = Field(default=None, description="Custom categories for classification.")
    custom_instructions: Optional[str] = Field(default=None, description="Custom instructions for fact extraction.")


class SearchMemoryRequest(BaseModel):
    query: str = Field(..., description="Search query.")
    user_id: Optional[str] = Field(default=None, description="Deprecated: pass inside `filters` instead.", deprecated=True)
    agent_id: Optional[str] = Field(default=None, description="Deprecated: pass inside `filters` instead.", deprecated=True)
    run_id: Optional[str] = Field(default=None, description="Deprecated: pass inside `filters` instead.", deprecated=True)
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Filters for the search.")
    top_k: Optional[int] = Field(default=None, description="Maximum number of results to return.")
    threshold: Optional[float] = Field(default=None, description="Minimum similarity score.")
    rerank: Optional[bool] = Field(default=None, description="Whether to rerank results.")
    keyword: Optional[bool] = Field(default=None, description="Enable keyword search.")
    fields: Optional[List[str]] = Field(default=None, description="Fields to include in response.")
    categories: Optional[List[str]] = Field(default=None, description="Categories to filter by.")
    explain: Optional[bool] = Field(default=None, description="Include score details.")


class UpdateMemoryRequest(BaseModel):
    text: Optional[str] = Field(default=None, description="New text content.")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Metadata to update.")
    timestamp: Optional[Union[int, float, str]] = Field(default=None, description="Updated timestamp.")


class GetAllMemoryRequest(BaseModel):
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Filters for retrieval.")
    page: Optional[int] = Field(default=None, description="Page number.")
    page_size: Optional[int] = Field(default=None, description="Items per page.")
    categories: Optional[List[str]] = Field(default=None, description="Categories to filter by.")
    start_date: Optional[str] = Field(default=None, description="Filter memories created on or after (ISO 8601).")
    end_date: Optional[str] = Field(default=None, description="Filter memories created on or before (ISO 8601).")


class DeleteAllMemoryRequest(BaseModel):
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Filters containing entity IDs.")


class FeedbackRequest(BaseModel):
    memory_id: str = Field(..., description="ID of the memory to provide feedback for.")
    feedback: Optional[str] = Field(default=None, description=f"Feedback value ({', '.join(FEEDBACK_VALUES)}).")
    feedback_reason: Optional[str] = Field(default=None, description="Reason for the feedback.")


class CreateMemoryExportRequest(BaseModel):
    schema: Dict[str, Any] = Field(..., description="JSON schema defining the export structure.")
    filters: Dict[str, Any] = Field(..., description="Filters to select which memories to export.")
    export_instructions: Optional[str] = Field(default=None, description="Additional instructions for the export.")


class GetMemoryExportRequest(BaseModel):
    memory_export_id: Optional[str] = Field(default=None, description="ID of the memory export to retrieve.")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Filters to identify the export.")


# ─── Response models (for API responses and SDK returns) ─────────────────────

class MemoryResponse(BaseModel):
    """Canonical memory response object.

    Used by:
    - Server REST API responses
    - Python SDK memory.get() / search() / get_all()
    - Vector store result formatting
    """

    id: str = Field(..., description="Unique identifier of the memory.")
    memory: str = Field(..., description="The memory content.")
    hash: Optional[str] = Field(default=None, description="Hash of the memory content.")
    user_id: Optional[str] = Field(default=None, description="ID of the user associated with the memory.")
    agent_id: Optional[str] = Field(default=None, description="ID of the agent associated with the memory.")
    run_id: Optional[str] = Field(default=None, description="ID of the run associated with the memory.")
    actor_id: Optional[str] = Field(default=None, description="ID of the actor that created the memory.")
    role: Optional[str] = Field(default=None, description="Role associated with the memory.")
    categories: Optional[List[str]] = Field(default=None, description="Categories for memory classification.")
    created_at: Optional[str] = Field(default=None, description="Timestamp when the memory was created.")
    updated_at: Optional[str] = Field(default=None, description="Timestamp when the memory was last updated.")
    expires_at: Optional[str] = Field(default=None, description="ISO 8601 timestamp when the memory expires.")
    ttl_state: Optional[str] = Field(default=None, description='TTL lifecycle state: "active" | "expiring_soon" | "expired" | "permanent".')
    ttl_source: Optional[str] = Field(default=None, description='Which policy scope produced expires_at: "default" | "category" | "user" | "agent" | "workspace" | "request".')
    score: Optional[float] = Field(default=None, description="Similarity score (only in search results).")
    feedback_status: Optional[str] = Field(default=None, description="Feedback status of the memory.")
    operation_id: Optional[str] = Field(default=None, description="Operation ID associated with the memory.")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata.")
    score_details: Optional[Dict[str, Any]] = Field(default=None, description="Detailed score breakdown (when explain=True).")


class MemoryHistoryItem(BaseModel):
    """A single history entry for a memory."""

    id: str = Field(..., description="Unique identifier of the history entry.")
    memory_id: str = Field(..., description="ID of the memory this history entry belongs to.")
    old_memory: Optional[str] = Field(default=None, description="Previous memory content.")
    new_memory: Optional[str] = Field(default=None, description="New memory content.")
    event: str = Field(..., description="Type of event (ADD, UPDATE, DELETE).")
    created_at: Optional[str] = Field(default=None, description="Timestamp when the event was created.")
    updated_at: Optional[str] = Field(default=None, description="Timestamp when the event was last updated.")
    is_deleted: bool = Field(default=False, description="Whether the memory was deleted.")
    actor_id: Optional[str] = Field(default=None, description="ID of the actor that performed the change.")
    role: Optional[str] = Field(default=None, description="Role associated with the change.")


class MemoryListResponse(BaseModel):
    """Response for list/search endpoints that return multiple memories."""

    results: List[MemoryResponse] = Field(..., description="List of memory results.")


# ─── SDK option models (for client method parameters) ────────────────────────
#
# These are the typed option objects passed to MemoryClient methods.
# They use "filters" instead of top-level entity IDs, matching the
# platform client API pattern.

class AddMemoryOptions(BaseModel):
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Filters containing entity IDs (e.g. {'user_id': '...'})")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata for the memory")
    infer: Optional[bool] = Field(default=None, description="Whether to infer memories from the input")
    custom_categories: Optional[List[Dict[str, Any]]] = Field(default=None, description="Custom categories for memory classification")
    custom_instructions: Optional[str] = Field(default=None, description="Custom instructions for fact extraction")
    timestamp: Optional[int] = Field(default=None, description="Unix timestamp for the memory")
    structured_data_schema: Optional[Dict[str, Any]] = Field(default=None, description="Schema for structured data extraction")
    expires: Optional[str] = Field(default=None, description="Expiration date (YYYY-MM-DD)")
    categories: Optional[List[str]] = Field(default=None, description="Categories for memory classification")
    immutable: Optional[bool] = Field(default=None, description="Mark memory as immutable")


class SearchMemoryOptions(BaseModel):
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Filters for the search (e.g. {'user_id': '...'})")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata for the search")
    top_k: Optional[int] = Field(default=None, description="Number of results to return")
    rerank: Optional[bool] = Field(default=None, description="Whether to rerank results")
    threshold: Optional[float] = Field(default=None, description="Minimum similarity score threshold")
    fields: Optional[List[str]] = Field(default=None, description="Fields to include in the response")
    categories: Optional[List[str]] = Field(default=None, description="Categories to filter by")


class GetAllMemoryOptions(BaseModel):
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Filters for retrieval (e.g. {'user_id': '...'})")
    page: Optional[int] = Field(default=None, description="Page number for pagination")
    page_size: Optional[int] = Field(default=None, description="Number of items per page")
    start_date: Optional[str] = Field(default=None, description="Filter memories created on or after this date (ISO 8601)")
    end_date: Optional[str] = Field(default=None, description="Filter memories created on or before this date (ISO 8601)")
    categories: Optional[List[str]] = Field(default=None, description="Categories to filter by")


class DeleteAllMemoryOptions(BaseModel):
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Filters containing entity IDs (e.g. {'user_id': '...'})")


class UpdateMemoryOptions(BaseModel):
    text: Optional[str] = Field(default=None, description="New text content for the memory")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Updated metadata")
    timestamp: Optional[Union[int, float, str]] = Field(default=None, description="Updated timestamp")


class FeedbackOptions(BaseModel):
    feedback: Optional[str] = Field(default=None, description=f"Feedback value ({', '.join(FEEDBACK_VALUES)})")
    feedback_reason: Optional[str] = Field(default=None, description="Reason for the feedback")


class CreateMemoryExportOptions(BaseModel):
    schema: Dict[str, Any] = Field(..., description="JSON schema defining the export structure")
    filters: Dict[str, Any] = Field(..., description="Filters to select which memories to export")
    export_instructions: Optional[str] = Field(default=None, description="Additional instructions for the export")


class GetMemoryExportOptions(BaseModel):
    memory_export_id: Optional[str] = Field(default=None, description="ID of the memory export to retrieve")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Filters to identify the export")


class ProjectUpdateOptions(BaseModel):
    custom_instructions: Optional[str] = Field(default=None, description="Custom instructions for fact extraction")
    custom_categories: Optional[List[Dict[str, Any]]] = Field(default=None, description="Custom categories for classification")
    memory_depth: Optional[str] = Field(default=None, description="Memory depth configuration")
    usecase_setting: Optional[Any] = Field(default=None, description="Use case specific settings")
    multilingual: Optional[bool] = Field(default=None, description="Whether to enable multilingual support")
    retrieval_criteria: Optional[List[Any]] = Field(default=None, description="Criteria for memory retrieval")

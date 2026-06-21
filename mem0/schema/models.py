"""Pydantic models derived from the canonical field definitions.

Server schemas and SDK option types should import these models rather than
redefining fields with potentially different names, defaults, or validators.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from mem0.schema.fields import (
    ADD_FIELD_SPECS,
    DELETE_ALL_FIELD_SPECS,
    ENTITY_FIELD_SET,
    FIELD_DEFAULTS,
    GET_ALL_FIELD_SPECS,
    SEARCH_FIELD_SPECS,
    UPDATE_FIELD_SPECS,
)


def _spec_to_field_kwargs(spec) -> dict:
    kw: dict = {"default": spec.default, "description": spec.description}
    if spec.default is None and not spec.required:
        kw["default"] = None
    return kw


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


class ProjectUpdateOptions(BaseModel):
    custom_instructions: Optional[str] = Field(default=None, description="Custom instructions for fact extraction")
    custom_categories: Optional[List[Dict[str, Any]]] = Field(default=None, description="Custom categories for classification")
    memory_depth: Optional[str] = Field(default=None, description="Memory depth configuration")
    usecase_setting: Optional[Any] = Field(default=None, description="Use case specific settings")
    multilingual: Optional[bool] = Field(default=None, description="Whether to enable multilingual support")
    retrieval_criteria: Optional[List[Any]] = Field(default=None, description="Criteria for memory retrieval")

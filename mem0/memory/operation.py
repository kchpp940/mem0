"""Unified operation pipeline for memory operations.

This module centralizes the common request normalization, payload processing,
result formatting, and lifecycle management (telemetry, notices) that was
previously duplicated across add/search/get_all/update/delete methods.

Public API behavior is preserved — these are internal helpers only.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from mem0.configs.base import MemoryItem
from mem0.memory.lifecycle import (
    LifecyclePolicy,
    annotate_memory_result,
    resolve_expiration,
)
from mem0.memory.utils import process_telemetry_filters


ENTITY_PARAMS = frozenset({"user_id", "agent_id", "run_id"})

PROMOTED_PAYLOAD_KEYS = [
    "user_id",
    "agent_id",
    "run_id",
    "actor_id",
    "role",
]

CORE_AND_PROMOTED_KEYS = {
    "data",
    "hash",
    "created_at",
    "updated_at",
    "id",
    "text_lemmatized",
    "attributed_to",
    "expires_at",
    "ttl_source",
    *PROMOTED_PAYLOAD_KEYS,
}


@dataclass
class MemoryRequestContext:
    """Normalized request context for all memory operations.

    Holds the validated, trimmed, and normalized state that flows through
    the operation pipeline. Constructed via PayloadNormalizer.
    """

    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    run_id: Optional[str] = None
    actor_id: Optional[str] = None

    filters: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    operation: str = ""
    sync_type: str = "sync"

    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def session_scope(self) -> str:
        """Build deterministic session scope string from entity IDs."""
        parts = []
        for key in sorted(["user_id", "agent_id", "run_id"]):
            val = getattr(self, key)
            if val:
                parts.append(f"{key}={val}")
        return "&".join(parts)

    @property
    def entity_filters(self) -> Dict[str, Any]:
        """Filters containing only user_id/agent_id/run_id (for vector store searches)."""
        return {k: v for k, v in self.filters.items() if k in ENTITY_PARAMS and v}

    def telemetry_payload(self, **extra) -> Dict[str, Any]:
        """Build telemetry event payload with common fields pre-populated."""
        keys, encoded_ids = process_telemetry_filters(self.filters)
        payload = {
            "keys": keys,
            "encoded_ids": encoded_ids,
            "sync_type": self.sync_type,
        }
        payload.update(extra)
        return payload


class PayloadNormalizer:
    """Normalizes and validates request payloads for memory operations.

    Centralizes:
    - Entity ID validation and trimming
    - Filter construction and validation
    - Metadata cleansing and augmentation
    - Lifecycle/expiration policy resolution
    - Rejection of legacy top-level entity params
    """

    @staticmethod
    def validate_and_trim_entity_id(value: Optional[str], name: str) -> Optional[str]:
        """Validate and normalize an entity ID (user_id, agent_id, run_id)."""
        if value is None:
            return None
        trimmed = value.strip()
        if trimmed == "":
            raise ValueError(
                f"Invalid {name}: cannot be empty or whitespace-only. Provide a valid identifier."
            )
        if any(c.isspace() for c in trimmed):
            raise ValueError(
                f"Invalid {name}: cannot contain whitespace. Provide a valid identifier without spaces."
            )
        return trimmed

    @staticmethod
    def validate_search_params(
        threshold: Optional[float] = None, top_k: Optional[int] = None
    ) -> None:
        """Validate search-specific parameters."""
        if threshold is not None:
            if not isinstance(threshold, (int, float)):
                raise ValueError("threshold must be a valid number")
            if threshold < 0 or threshold > 1:
                raise ValueError(
                    f"Invalid threshold: {threshold}. Must be between 0 and 1 (inclusive)."
                )
        if top_k is not None:
            if not isinstance(top_k, int) or isinstance(top_k, bool):
                raise ValueError("top_k must be a valid integer")
            if top_k < 0:
                raise ValueError(
                    f"Invalid top_k: {top_k}. Must be a non-negative integer."
                )

    @staticmethod
    def validate_and_trim_search_query(query: str) -> str:
        """Validate and normalize a search query."""
        if not isinstance(query, str):
            raise ValueError("Invalid query: must be a non-empty string.")
        trimmed = query.strip()
        if not trimmed:
            raise ValueError("Invalid query: cannot be empty or whitespace-only.")
        return trimmed

    @staticmethod
    def reject_top_level_entity_params(kwargs: Dict[str, Any], method_name: str) -> None:
        """Reject top-level entity parameters — they must use filters dict instead."""
        invalid_keys = ENTITY_PARAMS & set(kwargs.keys())
        if invalid_keys:
            raise ValueError(
                f"Top-level entity parameters {invalid_keys} are not supported in {method_name}(). "
                f"Use filters={{'user_id': '...'}} instead."
            )

    @staticmethod
    def build_filters_and_metadata(
        *,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        run_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        input_metadata: Optional[Dict[str, Any]] = None,
        input_filters: Optional[Dict[str, Any]] = None,
        require_entity_id: bool = True,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Build metadata template and query filters from entity identifiers.

        Returns:
            (base_metadata_template, effective_query_filters)
        """
        from mem0.exceptions import ValidationError as Mem0ValidationError

        base_metadata_template = deepcopy(input_metadata) if input_metadata else {}
        effective_query_filters = deepcopy(input_filters) if input_filters else {}

        session_ids_provided = []

        user_id = PayloadNormalizer.validate_and_trim_entity_id(user_id, "user_id")
        agent_id = PayloadNormalizer.validate_and_trim_entity_id(agent_id, "agent_id")
        run_id = PayloadNormalizer.validate_and_trim_entity_id(run_id, "run_id")

        if user_id:
            base_metadata_template["user_id"] = user_id
            effective_query_filters["user_id"] = user_id
            session_ids_provided.append("user_id")

        if agent_id:
            base_metadata_template["agent_id"] = agent_id
            effective_query_filters["agent_id"] = agent_id
            session_ids_provided.append("agent_id")

        if run_id:
            base_metadata_template["run_id"] = run_id
            effective_query_filters["run_id"] = run_id
            session_ids_provided.append("run_id")

        if require_entity_id and not session_ids_provided:
            raise Mem0ValidationError(
                message="At least one of 'user_id', 'agent_id', or 'run_id' must be provided.",
                error_code="VALIDATION_001",
                details={
                    "provided_ids": {
                        "user_id": user_id,
                        "agent_id": agent_id,
                        "run_id": run_id,
                    }
                },
                suggestion="Please provide at least one identifier to scope the memory operation.",
            )

        resolved_actor_id = actor_id or effective_query_filters.get("actor_id")
        if resolved_actor_id:
            effective_query_filters["actor_id"] = resolved_actor_id

        return base_metadata_template, effective_query_filters

    @staticmethod
    def normalize_filters_dict(filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Normalize a filters dict: trim entity IDs, validate presence."""
        effective_filters = dict(filters) if filters else {}

        for entity_key in ("user_id", "agent_id", "run_id"):
            if entity_key in effective_filters:
                effective_filters[entity_key] = (
                    PayloadNormalizer.validate_and_trim_entity_id(
                        effective_filters[entity_key], entity_key
                    )
                )

        if not any(key in effective_filters for key in ENTITY_PARAMS):
            raise ValueError(
                "filters must contain at least one of: user_id, agent_id, run_id. "
                "Example: filters={'user_id': 'u1'}"
            )

        return effective_filters

    @staticmethod
    def resolve_lifecycle(
        config,
        expires: Optional[Any] = None,
        ttl_days: Optional[int] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Resolve expiration from request params and config policies.

        Returns:
            (effective_expires_at_iso, ttl_source_value) or (None, None) if no TTL applies.
        """
        lifecycle_cfg = getattr(config, "lifecycle_policies", None)
        default_policy = (
            LifecyclePolicy.from_dict(lifecycle_cfg.default.model_dump())
            if lifecycle_cfg and getattr(lifecycle_cfg, "default", None)
            else None
        )
        workspace_policy = (
            LifecyclePolicy.from_dict(lifecycle_cfg.workspace.model_dump())
            if lifecycle_cfg and getattr(lifecycle_cfg, "workspace", None)
            else None
        )

        effective_expires_at, effective_ttl_source = resolve_expiration(
            request_expires=expires,
            request_ttl_days=ttl_days,
            workspace_policy=workspace_policy,
            default_policy=default_policy,
        )

        return effective_expires_at, effective_ttl_source.value if effective_ttl_source else None

    @staticmethod
    def for_add(
        *,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        expires: Optional[Any] = None,
        ttl_days: Optional[int] = None,
        config=None,
        sync_type: str = "sync",
    ) -> MemoryRequestContext:
        """Build a request context for an add() operation."""
        processed_metadata, effective_filters = PayloadNormalizer.build_filters_and_metadata(
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            input_metadata=metadata,
        )

        if config is not None and (expires is not None or ttl_days is not None):
            effective_expires_at, effective_ttl_source = PayloadNormalizer.resolve_lifecycle(
                config, expires=expires, ttl_days=ttl_days
            )
            if effective_expires_at is not None:
                processed_metadata["expires_at"] = effective_expires_at
                processed_metadata["ttl_source"] = effective_ttl_source

        trimmed_user_id = effective_filters.get("user_id")
        trimmed_agent_id = effective_filters.get("agent_id")
        trimmed_run_id = effective_filters.get("run_id")

        return MemoryRequestContext(
            user_id=trimmed_user_id,
            agent_id=trimmed_agent_id,
            run_id=trimmed_run_id,
            filters=effective_filters,
            metadata=processed_metadata,
            operation="add",
            sync_type=sync_type,
        )

    @staticmethod
    def for_search(
        *,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 20,
        threshold: float = 0.1,
        sync_type: str = "sync",
        **kwargs,
    ) -> MemoryRequestContext:
        """Build a request context for a search() operation."""
        PayloadNormalizer.reject_top_level_entity_params(kwargs, "search")
        PayloadNormalizer.validate_search_params(threshold=threshold, top_k=top_k)
        normalized_query = PayloadNormalizer.validate_and_trim_search_query(query)
        effective_filters = PayloadNormalizer.normalize_filters_dict(filters)

        return MemoryRequestContext(
            user_id=effective_filters.get("user_id"),
            agent_id=effective_filters.get("agent_id"),
            run_id=effective_filters.get("run_id"),
            actor_id=effective_filters.get("actor_id"),
            filters=effective_filters,
            operation="search",
            sync_type=sync_type,
            extra={"query": normalized_query, "top_k": top_k, "threshold": threshold},
        )

    @staticmethod
    def for_get_all(
        *,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 20,
        sync_type: str = "sync",
        **kwargs,
    ) -> MemoryRequestContext:
        """Build a request context for a get_all() operation."""
        PayloadNormalizer.reject_top_level_entity_params(kwargs, "get_all")
        PayloadNormalizer.validate_search_params(top_k=top_k)
        effective_filters = PayloadNormalizer.normalize_filters_dict(filters)

        return MemoryRequestContext(
            user_id=effective_filters.get("user_id"),
            agent_id=effective_filters.get("agent_id"),
            run_id=effective_filters.get("run_id"),
            filters=effective_filters,
            operation="get_all",
            sync_type=sync_type,
            extra={"top_k": top_k},
        )


class ResultFormatter:
    """Formats raw vector store results into the public API response format.

    Centralizes the conversion from vector store payloads to MemoryItem dicts,
    including promoted fields extraction, metadata separation, and TTL annotation.
    """

    @staticmethod
    def format_memory_item(
        payload: Dict[str, Any],
        memory_id: str,
        score: Optional[float] = None,
        score_details: Optional[Dict[str, Any]] = None,
        include_score: bool = True,
    ) -> Dict[str, Any]:
        """Format a single memory payload into the public API response format.

        Args:
            payload: Raw vector store payload dict
            memory_id: Memory ID string
            score: Similarity score (for search results)
            score_details: Score breakdown (when explain=True)
            include_score: Whether to include score field in output

        Returns:
            Formatted memory dict matching the MemoryItem schema
        """
        model_dump_kwargs = {}
        if not include_score:
            model_dump_kwargs["exclude"] = {"score"}

        memory_item_dict = MemoryItem(
            id=memory_id,
            memory=payload.get("data", ""),
            hash=payload.get("hash"),
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
            expires_at=payload.get("expires_at"),
            ttl_source=payload.get("ttl_source"),
            score=score,
        ).model_dump(**model_dump_kwargs)

        for key in PROMOTED_PAYLOAD_KEYS:
            if key in payload:
                memory_item_dict[key] = payload[key]

        additional_metadata = {
            k: v for k, v in payload.items() if k not in CORE_AND_PROMOTED_KEYS
        }
        if additional_metadata:
            if not memory_item_dict.get("metadata"):
                memory_item_dict["metadata"] = {}
            memory_item_dict["metadata"].update(additional_metadata)

        if score_details is not None:
            memory_item_dict["score_details"] = score_details

        annotate_memory_result(memory_item_dict)

        return memory_item_dict

    @staticmethod
    def format_search_results(scored_results: list, explain: bool = False) -> list:
        """Format scored search results into public API format.

        Args:
            scored_results: List of dicts with id, score, payload, optional score_details
            explain: Whether to include score_details

        Returns:
            List of formatted memory dicts
        """
        formatted = []
        for scored in scored_results:
            payload = scored.get("payload") or {}

            if not payload.get("data"):
                continue

            score_details = scored.get("score_details") if explain else None
            formatted.append(
                ResultFormatter.format_memory_item(
                    payload=payload,
                    memory_id=scored["id"],
                    score=scored["score"],
                    score_details=score_details,
                    include_score=True,
                )
            )
        return formatted

    @staticmethod
    def format_list_results(memories: list) -> list:
        """Format vector store list results into public API format.

        Handles different vector store return formats (tuples, nested lists, etc.)
        and normalizes them to a flat list of formatted memory dicts.

        Args:
            memories: Raw result from vector_store.list()

        Returns:
            List of formatted memory dicts
        """
        if isinstance(memories, (tuple, list)) and len(memories) > 0:
            first_element = memories[0]
            if isinstance(first_element, (list, tuple)):
                actual_memories = first_element
            else:
                actual_memories = memories
        else:
            actual_memories = memories

        formatted = []
        for mem in actual_memories:
            payload = mem.payload if hasattr(mem, "payload") else {}
            memory_id = str(mem.id) if hasattr(mem, "id") else str(payload.get("id", ""))

            formatted.append(
                ResultFormatter.format_memory_item(
                    payload=payload,
                    memory_id=memory_id,
                    include_score=True,
                )
            )
        return formatted

    @staticmethod
    def wrap_results(results: list) -> Dict[str, Any]:
        """Wrap a list of results in the standard {"results": [...]} envelope."""
        return {"results": results}


class OperationLifecycle:
    """Handles cross-cutting concerns: telemetry, notices, and lifecycle events.

    Provides a unified interface for:
    - Capturing telemetry events with consistent payloads
    - Displaying usage notices (first run, scale thresholds, temporal/decay features)
    - Timing operations for performance monitoring
    """

    @staticmethod
    def capture_event(event_name: str, memory_instance, ctx: MemoryRequestContext, **extra) -> None:
        """Capture a telemetry event with context-derived payload."""
        from mem0.memory.telemetry import capture_event

        payload = ctx.telemetry_payload(**extra)
        capture_event(event_name, memory_instance, payload)

    @staticmethod
    def detect_add_notices(memory_instance, results: list, temporal_notice: Optional[tuple] = None):
        """Detect and return the appropriate notice for an add operation."""
        from mem0.memory.main import detect_scale_threshold_from_add_result

        if temporal_notice:
            return "temporal", temporal_notice
        scale_notice = detect_scale_threshold_from_add_result(memory_instance, results)
        if scale_notice:
            return "scale", scale_notice
        return "first_run", None

    @staticmethod
    async def detect_add_notices_async(memory_instance, results: list, temporal_notice: Optional[tuple] = None):
        """Detect and return the appropriate notice for an async add operation (scale detection in thread)."""
        import asyncio

        from mem0.memory.main import detect_scale_threshold_from_add_result

        if temporal_notice:
            return "temporal", temporal_notice
        scale_notice = await asyncio.to_thread(detect_scale_threshold_from_add_result, memory_instance, results)
        if scale_notice:
            return "scale", scale_notice
        return "first_run", None

    @staticmethod
    def detect_search_notices(
        memory_instance,
        top_k: int,
        elapsed_seconds: float,
        result_count: int,
        temporal_notice: Optional[tuple] = None,
    ):
        """Detect and return the appropriate notice for a search operation."""
        from mem0.memory.main import (
            PERFORMANCE_SLOW_QUERY_THRESHOLD_SECONDS,
            detect_scale_threshold_from_top_k,
        )

        if temporal_notice:
            return "temporal", temporal_notice
        scale_notice = detect_scale_threshold_from_top_k(top_k)
        if scale_notice:
            return "scale", scale_notice
        if elapsed_seconds > PERFORMANCE_SLOW_QUERY_THRESHOLD_SECONDS:
            return "performance", (elapsed_seconds, top_k, result_count)
        return "first_run", None

    @staticmethod
    def detect_get_all_notices(memory_instance, top_k: int):
        """Detect and return the appropriate notice for a get_all operation."""
        from mem0.memory.main import detect_scale_threshold_from_top_k

        scale_notice = detect_scale_threshold_from_top_k(top_k)
        if scale_notice:
            return "scale", scale_notice
        return "first_run", None

    @staticmethod
    def detect_delete_notices(decay_notice: Optional[tuple] = None):
        """Detect and return the appropriate notice for a delete operation."""
        if decay_notice:
            return "decay", decay_notice
        return "first_run", None

    @staticmethod
    def detect_delete_all_notices(decay_notice: Optional[tuple] = None):
        """Detect and return the appropriate notice for a delete_all operation."""
        if decay_notice:
            return "decay", decay_notice
        return "first_run", None

    @staticmethod
    def dispatch_notice(
        memory_instance,
        notice_type: str,
        notice_args: tuple,
        sync_type: str,
        operation: str,
    ) -> None:
        """Dispatch a notice to the appropriate display function (sync)."""
        from mem0.memory.main import (
            display_decay_usage_notice,
            display_first_run_notice,
            display_performance_slow_query_notice,
            display_scale_threshold_notice,
            display_temporal_usage_notice,
        )

        if notice_type == "temporal":
            display_temporal_usage_notice(memory_instance, sync_type, operation, *notice_args)
        elif notice_type == "scale":
            display_scale_threshold_notice(memory_instance, sync_type, operation, *notice_args)
        elif notice_type == "performance":
            display_performance_slow_query_notice(memory_instance, sync_type, operation, *notice_args)
        elif notice_type == "decay":
            display_decay_usage_notice(memory_instance, sync_type, operation, *notice_args)
        elif notice_type == "first_run":
            display_first_run_notice(memory_instance, sync_type, operation)

    @staticmethod
    async def dispatch_notice_async(
        memory_instance,
        notice_type: str,
        notice_args: tuple,
        sync_type: str,
        operation: str,
    ) -> None:
        """Dispatch a notice to the appropriate display function (async)."""
        import asyncio
        from mem0.memory.main import (
            display_decay_usage_notice_async,
            display_first_run_notice_async,
            display_performance_slow_query_notice_async,
            display_scale_threshold_notice_async,
            display_temporal_usage_notice_async,
            detect_scale_threshold_from_add_result,
        )

        if notice_type == "temporal":
            await display_temporal_usage_notice_async(memory_instance, sync_type, operation, *notice_args)
        elif notice_type == "scale":
            scale_notice = await asyncio.to_thread(
                detect_scale_threshold_from_add_result, memory_instance, notice_args
            ) if isinstance(notice_args, list) else notice_args
            if isinstance(notice_args, list):
                await display_scale_threshold_notice_async(memory_instance, sync_type, operation, *scale_notice)
            else:
                await display_scale_threshold_notice_async(memory_instance, sync_type, operation, *notice_args)
        elif notice_type == "performance":
            await display_performance_slow_query_notice_async(memory_instance, sync_type, operation, *notice_args)
        elif notice_type == "decay":
            await display_decay_usage_notice_async(memory_instance, sync_type, operation, *notice_args)
        elif notice_type == "first_run":
            await display_first_run_notice_async(memory_instance, sync_type, operation)

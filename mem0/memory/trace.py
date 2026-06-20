"""
Memory operation tracing for debugging and performance analysis.

This module provides structured tracing for memory operations (add/search/list)
without exposing sensitive data like raw text, prompts, or internal index fields.
Only non-identifiable statistics and timing information are collected.

Public API:
    - OperationTrace: Complete trace for a single memory operation
    - TraceStage: Individual stage within an operation
    - TraceCollector: Context manager for collecting trace data
    - create_trace_collector: Factory function to create a trace collector
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


# Stage names for memory operations
STAGE_LLM_EXTRACTION = "llm_extraction"
STAGE_EMBEDDING = "embedding"
STAGE_VECTOR_STORE = "vector_store"
STAGE_KEYWORD_RECALL = "keyword_recall"
STAGE_ENTITY_RECALL = "entity_recall"
STAGE_ENTITY_LINKING = "entity_linking"
STAGE_SCORE_FUSION = "score_fusion"
STAGE_FORMATTER = "formatter"
STAGE_HISTORY = "history"
STAGE_CONTEXT_GATHERING = "context_gathering"
STAGE_DEDUP = "deduplication"

STAGE_NAMES = {
    STAGE_LLM_EXTRACTION,
    STAGE_EMBEDDING,
    STAGE_VECTOR_STORE,
    STAGE_KEYWORD_RECALL,
    STAGE_ENTITY_RECALL,
    STAGE_ENTITY_LINKING,
    STAGE_SCORE_FUSION,
    STAGE_FORMATTER,
    STAGE_HISTORY,
    STAGE_CONTEXT_GATHERING,
    STAGE_DEDUP,
}


_SAFE_VALUE_TYPES = (int, float, bool)
_SAFE_ENUM_STRINGS = {
    # mode values
    "search", "batch_add", "add",
    # operation values
    "search", "insert", "list", "semantic_search", "search_existing",
    # generic
    "true", "false",
}


ALLOWED_METADATA_KEYS = {
    # counts / quantities
    "count",
    "inserted",
    "processed",
    "failed",
    "records_saved",
    "existing_retrieved",
    "extracted_count",
    "duplicates_skipped",
    "memories_added",
    "memories_updated",
    "memories_skipped",
    "entities_extracted",
    "entities_linked",
    "entity_matches",
    "semantic_candidates",
    "keyword_candidates",
    "candidates_ranked",
    "candidates_passed_threshold",
    "results_filtered",
    "results_returned",
    "last_messages_count",
    "existing_memories",
    # flags / booleans
    "batch",
    "infer",
    "supported",
    "has_bm25",
    "has_entity_boost",
    # configuration / parameters
    "mode",
    "operation",
    "threshold",
    "internal_limit",
}


def sanitize_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Centralized metadata sanitizer for trace stages.

    Policy:
      - Only keys in ALLOWED_METADATA_KEYS are retained.
      - Only values of type int, float, bool, or short enum-like strings are retained.
      - All other keys are silently dropped — no sensitive data ever reaches trace output.
      - Returns a new dict; the input is never mutated.
    """
    if not metadata:
        return {}

    clean: Dict[str, Any] = {}
    for key, value in metadata.items():
        if key not in ALLOWED_METADATA_KEYS:
            continue
        if isinstance(value, _SAFE_VALUE_TYPES):
            clean[key] = value
        elif isinstance(value, str):
            # Only accept short, enum-like strings (<= 32 chars).
            # If it looks like free-form text (contains spaces, long, etc.), drop it.
            lowered = value.lower()
            if len(value) <= 32 and (" " not in value) and lowered in _SAFE_ENUM_STRINGS:
                clean[key] = lowered
        # dict/list and everything else (embeddings, raw text, objects) are dropped
    return clean


def sanitize_error(error: Optional[str]) -> Optional[str]:
    """Sanitize an error message so it never contains user content.

    Policy: keep only the exception class name or very short predefined tokens.
    Long or free-form strings are replaced with "[redacted]".
    """
    if not error:
        return None
    if len(error) <= 64 and " " not in error and ("." not in error or error.count(".") < 2):
        # Looks like an exception class name (e.g. "LLMError", "ValueError")
        return error
    return "[redacted]"


@dataclass
class TraceStage:
    """A single stage within a memory operation trace.

    Stores only non-sensitive, structured information for debugging.
    No raw text, prompts, or embeddings are ever stored.
    """

    name: str
    start_time: float
    end_time: float = 0.0
    duration_ms: float = 0.0
    status: str = "pending"  # pending, success, skipped, error
    metadata: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None

    def __post_init__(self) -> None:
        """Sanitize any metadata that was passed in via dataclass construction."""
        if self.metadata:
            self.metadata = sanitize_metadata(self.metadata)
        if self.error_message:
            self.error_message = sanitize_error(self.error_message)

    def finish(self, status: str = "success", metadata: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> None:
        """Mark the stage as finished and record duration.

        Args:
            status: "success", "skipped", or "error"
            metadata: Non-sensitive statistics about this stage (will be sanitized)
            error: Error message if status is "error" (will be sanitized)
        """
        self.end_time = time.perf_counter()
        self.duration_ms = round((self.end_time - self.start_time) * 1000, 2)
        self.status = status
        if metadata:
            self.metadata.update(sanitize_metadata(metadata))
        if error:
            self.error_message = sanitize_error(error)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a serializable dictionary.

        Metadata is always sanitized at the output boundary for defense in depth.
        """
        return {
            "name": self.name,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "metadata": sanitize_metadata(self.metadata),
            "error": sanitize_error(self.error_message),
        }


@dataclass
class OperationTrace:
    """Complete trace for a single memory operation.

    Contains:
    - operation_id: Unique identifier for this operation
    - operation_type: "add", "search", or "list"
    - stages: Ordered list of TraceStage objects
    - summary: Aggregated statistics for quick inspection
    - created_at: ISO timestamp when the trace was created
    """

    operation_id: str
    operation_type: str
    created_at: str
    stages: List[TraceStage] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    _current_stage: Optional[TraceStage] = field(default=None, repr=False)

    def start_stage(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> TraceStage:
        """Start timing a new stage.

        Args:
            name: Stage name from STAGE_NAMES
            metadata: Initial metadata for the stage

        Returns:
            The newly created TraceStage
        """
        stage = TraceStage(
            name=name,
            start_time=time.perf_counter(),
            metadata=metadata or {},
        )
        self.stages.append(stage)
        self._current_stage = stage
        return stage

    def finish_current_stage(self, status: str = "success", metadata: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> None:
        """Finish the currently active stage."""
        if self._current_stage:
            self._current_stage.finish(status=status, metadata=metadata, error=error)
            self._current_stage = None

    def finish_stage(
        self,
        stage: TraceStage,
        status: str = "success",
        metadata: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """Finish a specific stage.

        Args:
            stage: The stage to finish
            status: "success", "skipped", or "error"
            metadata: Additional metadata to add
            error: Error message if failed
        """
        stage.finish(status=status, metadata=metadata, error=error)
        if self._current_stage is stage:
            self._current_stage = None

    def build_summary(self) -> Dict[str, Any]:
        """Build an aggregated summary of the trace.

        Returns:
            Dictionary with total duration, stage breakdown, and key statistics.
            Only whitelisted metadata keys are included in the decisions section.
        """
        total_ms = round(sum(s.duration_ms for s in self.stages), 2)
        stage_breakdown = {s.name: s.duration_ms for s in self.stages}
        successful = sum(1 for s in self.stages if s.status == "success")
        skipped = sum(1 for s in self.stages if s.status == "skipped")
        errors = sum(1 for s in self.stages if s.status == "error")

        _SUMMARY_DECISION_KEYS = {
            "extracted_count",
            "duplicates_skipped",
            "semantic_candidates",
            "keyword_candidates",
            "entity_matches",
            "entities_extracted",
            "entities_linked",
            "candidates_ranked",
            "results_filtered",
            "results_returned",
            "candidates_passed_threshold",
        }

        # Collect key decision statistics from stage metadata — only whitelisted keys
        decisions: Dict[str, Any] = {}
        for s in self.stages:
            clean_meta = sanitize_metadata(s.metadata)
            for k, v in clean_meta.items():
                if k in _SUMMARY_DECISION_KEYS:
                    decisions[f"{s.name}_{k}"] = v

        self.summary = {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "created_at": self.created_at,
            "total_duration_ms": total_ms,
            "stage_count": len(self.stages),
            "successful_stages": successful,
            "skipped_stages": skipped,
            "error_stages": errors,
            "stage_breakdown_ms": stage_breakdown,
            "decisions": decisions,
        }
        return self.summary

    def to_dict(self, compact: bool = False) -> Dict[str, Any]:
        """Convert to a serializable dictionary.

        Args:
            compact: If True, return only the summary without individual stages.

        Returns:
            Serializable dictionary representation of the trace.
        """
        self.build_summary()
        if compact:
            return {"trace": self.summary}
        return {
            "trace": self.summary,
            "stages": [s.to_dict() for s in self.stages],
        }

    def format_compact(self) -> str:
        """Format the trace as a compact one-line string for CLI display."""
        self.build_summary()
        parts = [f"op_id={self.operation_id[:8]}"]
        parts.append(f"type={self.operation_type}")
        parts.append(f"total={self.summary.get('total_duration_ms', 0)}ms")

        # Add key stage timings
        key_stages = [
            STAGE_LLM_EXTRACTION,
            STAGE_EMBEDDING,
            STAGE_VECTOR_STORE,
            STAGE_SCORE_FUSION,
        ]
        for stage_name in key_stages:
            duration = self.summary.get("stage_breakdown_ms", {}).get(stage_name, 0)
            if duration > 0:
                parts.append(f"{stage_name}={duration}ms")

        # Add decisions
        decisions = self.summary.get("decisions", {})
        for key, value in decisions.items():
            if isinstance(value, (int, float)):
                # Shorten key names for compact display
                short_key = key.replace("_count", "").replace("_candidates", " cand")
                parts.append(f"{short_key}={value}")

        return " | ".join(parts)


class TraceCollector:
    """Context manager for collecting trace data during a memory operation.

    Usage:
        with create_trace_collector("search") as tracer:
            tracer.start_stage(STAGE_EMBEDDING)
            # ... do embedding work ...
            tracer.finish_current_stage(metadata={"tokens": 128})

            tracer.start_stage(STAGE_VECTOR_STORE)
            # ... do vector search ...
            tracer.finish_current_stage(metadata={"candidates": 50})

        result = {"results": [...], **tracer.get_trace_dict()}
    """

    def __init__(self, operation_type: str, enabled: bool = True, operation_id: Optional[str] = None):
        """Initialize the trace collector.

        Args:
            operation_type: "add", "search", or "list"
            enabled: Whether tracing is enabled (can be disabled for hot paths)
            operation_id: Optional external operation ID (e.g. from X-Operation-ID header).
                          If not provided, a UUID will be generated.
        """
        self.enabled = enabled
        self.operation_type = operation_type
        self.trace: Optional[OperationTrace] = None
        if enabled:
            self.trace = OperationTrace(
                operation_id=operation_id if operation_id else str(uuid.uuid4()),
                operation_type=operation_type,
                created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )

    def __enter__(self) -> "TraceCollector":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Ensure any unfinished stage is marked with error if an exception occurred."""
        if self.trace and self.trace._current_stage:
            if exc_val is not None:
                # Don't include the full exception message to avoid leaking sensitive data
                self.trace.finish_current_stage(status="error", error=f"{exc_type.__name__}")
            else:
                self.trace.finish_current_stage(status="success")

    def start_stage(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[TraceStage]:
        """Start a new stage if tracing is enabled."""
        if not self.enabled or self.trace is None:
            return None
        return self.trace.start_stage(name, metadata)

    def finish_current_stage(
        self,
        status: str = "success",
        metadata: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """Finish the current stage if tracing is enabled."""
        if not self.enabled or self.trace is None:
            return
        self.trace.finish_current_stage(status=status, metadata=metadata, error=error)

    def finish_stage(
        self,
        stage: Optional[TraceStage],
        status: str = "success",
        metadata: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """Finish a specific stage if tracing is enabled."""
        if not self.enabled or self.trace is None or stage is None:
            return
        self.trace.finish_stage(stage, status=status, metadata=metadata, error=error)

    def get_trace_dict(self, compact: bool = False) -> Dict[str, Any]:
        """Get the trace as a dictionary. Returns {} if tracing is disabled.

        Args:
            compact: If True, return only the summary without individual stages.
        """
        if not self.enabled or self.trace is None:
            return {}
        return self.trace.to_dict(compact=compact)

    def get_operation_id(self) -> Optional[str]:
        """Get the operation ID for this trace, or None if tracing is disabled."""
        if not self.enabled or self.trace is None:
            return None
        return self.trace.operation_id

    def format_compact(self) -> str:
        """Format the trace compactly for CLI display."""
        if not self.enabled or self.trace is None:
            return ""
        return self.trace.format_compact()


def create_trace_collector(
    operation_type: str,
    enabled: bool = True,
    operation_id: Optional[str] = None,
) -> TraceCollector:
    """Factory function to create a TraceCollector.

    Args:
        operation_type: "add", "search", or "list"
        enabled: Whether tracing should be enabled
        operation_id: Optional external operation ID (e.g. from X-Operation-ID header).
                      If not provided, a UUID will be generated.

    Returns:
        A new TraceCollector instance
    """
    return TraceCollector(
        operation_type=operation_type,
        enabled=enabled,
        operation_id=operation_id,
    )

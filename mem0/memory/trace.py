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

    def finish(self, status: str = "success", metadata: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> None:
        """Mark the stage as finished and record duration.

        Args:
            status: "success", "skipped", or "error"
            metadata: Non-sensitive statistics about this stage
            error: Error message if status is "error" (keep brief, no sensitive data)
        """
        self.end_time = time.perf_counter()
        self.duration_ms = round((self.end_time - self.start_time) * 1000, 2)
        self.status = status
        if metadata:
            self.metadata.update(metadata)
        if error:
            self.error_message = error

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a serializable dictionary."""
        return {
            "name": self.name,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "metadata": self.metadata,
            "error": self.error_message,
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
        """
        total_ms = round(sum(s.duration_ms for s in self.stages), 2)
        stage_breakdown = {s.name: s.duration_ms for s in self.stages}
        successful = sum(1 for s in self.stages if s.status == "success")
        skipped = sum(1 for s in self.stages if s.status == "skipped")
        errors = sum(1 for s in self.stages if s.status == "error")

        # Collect key decision statistics from stage metadata
        decisions: Dict[str, Any] = {}
        for s in self.stages:
            for k, v in s.metadata.items():
                if k in {
                    "extracted_count",
                    "duplicates_skipped",
                    "semantic_candidates",
                    "keyword_candidates",
                    "entity_matches",
                    "entities_extracted",
                    "candidates_ranked",
                    "results_filtered",
                    "candidates_passed_threshold",
                }:
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

    def __init__(self, operation_type: str, enabled: bool = True):
        """Initialize the trace collector.

        Args:
            operation_type: "add", "search", or "list"
            enabled: Whether tracing is enabled (can be disabled for hot paths)
        """
        self.enabled = enabled
        self.operation_type = operation_type
        self.trace: Optional[OperationTrace] = None
        if enabled:
            self.trace = OperationTrace(
                operation_id=str(uuid.uuid4()),
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


def create_trace_collector(operation_type: str, enabled: bool = True) -> TraceCollector:
    """Factory function to create a TraceCollector.

    Args:
        operation_type: "add", "search", or "list"
        enabled: Whether tracing should be enabled

    Returns:
        A new TraceCollector instance
    """
    return TraceCollector(operation_type=operation_type, enabled=enabled)

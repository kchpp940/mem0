"""
Hooks provider interface for OperationLifecycle.

This module provides a stable interface for telemetry and notice operations,
decoupling OperationLifecycle from the specific implementation details of
notices and telemetry. This eliminates the circular dependency where
operation.py needed to import from main.py for test compatibility.

The hooks pattern allows:
- OperationLifecycle to depend only on a stable interface
- Tests to inject mock hooks for verification
- Default implementation to live in notices/telemetry modules
- No circular imports between operation.py and main.py

For test compatibility with existing monkeypatch patterns, the default
hooks implementation can be configured to look up functions from a
specific module at runtime.
"""

from __future__ import annotations

import importlib
from typing import Any, Optional, Protocol, Tuple

from mem0.memory.telemetry import capture_event


class MemoryHooks(Protocol):
    """Protocol defining the hooks interface for operation lifecycle events.

    This interface abstracts cross-cutting concerns (telemetry, notices)
    so that OperationLifecycle does not depend on specific implementations.
    """

    def capture_telemetry(
        self, event_name: str, memory_instance: Any, payload: dict
    ) -> None:
        """Capture a telemetry event."""
        ...

    def detect_add_notice(
        self, memory_instance: Any, results: list, temporal_notice: Optional[tuple] = None
    ) -> Tuple[str, Optional[tuple]]:
        """Detect the appropriate notice type for an add operation."""
        ...

    async def detect_add_notice_async(
        self, memory_instance: Any, results: list, temporal_notice: Optional[tuple] = None
    ) -> Tuple[str, Optional[tuple]]:
        """Detect the appropriate notice type for an async add operation."""
        ...

    def detect_search_notice(
        self,
        memory_instance: Any,
        top_k: int,
        elapsed_seconds: float,
        result_count: int,
        temporal_notice: Optional[tuple] = None,
    ) -> Tuple[str, Optional[tuple]]:
        """Detect the appropriate notice type for a search operation."""
        ...

    def detect_get_all_notice(
        self, memory_instance: Any, top_k: int
    ) -> Tuple[str, Optional[tuple]]:
        """Detect the appropriate notice type for a get_all operation."""
        ...

    def detect_delete_notice(
        self, decay_notice: Optional[tuple] = None
    ) -> Tuple[str, Optional[tuple]]:
        """Detect the appropriate notice type for a delete operation."""
        ...

    def detect_delete_all_notice(
        self, decay_notice: Optional[tuple] = None
    ) -> Tuple[str, Optional[tuple]]:
        """Detect the appropriate notice type for a delete_all operation."""
        ...

    def dispatch_notice(
        self,
        memory_instance: Any,
        notice_type: str,
        notice_args: tuple,
        sync_type: str,
        operation: str,
    ) -> None:
        """Dispatch a notice to the appropriate display function (sync)."""
        ...

    async def dispatch_notice_async(
        self,
        memory_instance: Any,
        notice_type: str,
        notice_args: tuple,
        sync_type: str,
        operation: str,
    ) -> None:
        """Dispatch a notice to the appropriate display function (async)."""
        ...


class DefaultMemoryHooks:
    """Default implementation of MemoryHooks.

    Functions are looked up dynamically from a configurable module.
    Defaults to mem0.memory.notices, but can be set to mem0.memory.main
    for test compatibility with monkeypatch patterns.
    """

    _notice_module_name: str = "mem0.memory.notices"

    @classmethod
    def set_notice_module(cls, module_name: str) -> None:
        """Set the module name to import notice functions from.

        Used for test compatibility: set to "mem0.memory.main" so that
        monkeypatch on the main module can intercept notice calls.
        """
        cls._notice_module_name = module_name

    @classmethod
    def _get_notice_module(cls):
        return importlib.import_module(cls._notice_module_name)

    def capture_telemetry(
        self, event_name: str, memory_instance: Any, payload: dict
    ) -> None:
        capture_event(event_name, memory_instance, payload)

    def detect_add_notice(
        self, memory_instance: Any, results: list, temporal_notice: Optional[tuple] = None
    ) -> Tuple[str, Optional[tuple]]:
        notices = self._get_notice_module()
        detect_scale_threshold_from_add_result = notices.detect_scale_threshold_from_add_result

        if temporal_notice:
            return "temporal", temporal_notice
        scale_notice = detect_scale_threshold_from_add_result(memory_instance, results)
        if scale_notice:
            return "scale", scale_notice
        return "first_run", None

    async def detect_add_notice_async(
        self, memory_instance: Any, results: list, temporal_notice: Optional[tuple] = None
    ) -> Tuple[str, Optional[tuple]]:
        import asyncio

        notices = self._get_notice_module()
        detect_scale_threshold_from_add_result = notices.detect_scale_threshold_from_add_result

        if temporal_notice:
            return "temporal", temporal_notice
        scale_notice = await asyncio.to_thread(
            detect_scale_threshold_from_add_result, memory_instance, results
        )
        if scale_notice:
            return "scale", scale_notice
        return "first_run", None

    def detect_search_notice(
        self,
        memory_instance: Any,
        top_k: int,
        elapsed_seconds: float,
        result_count: int,
        temporal_notice: Optional[tuple] = None,
    ) -> Tuple[str, Optional[tuple]]:
        notices = self._get_notice_module()
        PERFORMANCE_SLOW_QUERY_THRESHOLD_SECONDS = notices.PERFORMANCE_SLOW_QUERY_THRESHOLD_SECONDS
        detect_scale_threshold_from_top_k = notices.detect_scale_threshold_from_top_k

        if temporal_notice:
            return "temporal", temporal_notice
        scale_notice = detect_scale_threshold_from_top_k(top_k)
        if scale_notice:
            return "scale", scale_notice
        if elapsed_seconds > PERFORMANCE_SLOW_QUERY_THRESHOLD_SECONDS:
            return "performance", (elapsed_seconds, top_k, result_count)
        return "first_run", None

    def detect_get_all_notice(
        self, memory_instance: Any, top_k: int
    ) -> Tuple[str, Optional[tuple]]:
        notices = self._get_notice_module()
        detect_scale_threshold_from_top_k = notices.detect_scale_threshold_from_top_k

        scale_notice = detect_scale_threshold_from_top_k(top_k)
        if scale_notice:
            return "scale", scale_notice
        return "first_run", None

    def detect_delete_notice(
        self, decay_notice: Optional[tuple] = None
    ) -> Tuple[str, Optional[tuple]]:
        if decay_notice:
            return "decay", decay_notice
        return "first_run", None

    def detect_delete_all_notice(
        self, decay_notice: Optional[tuple] = None
    ) -> Tuple[str, Optional[tuple]]:
        if decay_notice:
            return "decay", decay_notice
        return "first_run", None

    def dispatch_notice(
        self,
        memory_instance: Any,
        notice_type: str,
        notice_args: tuple,
        sync_type: str,
        operation: str,
    ) -> None:
        notices = self._get_notice_module()
        display_decay_usage_notice = notices.display_decay_usage_notice
        display_first_run_notice = notices.display_first_run_notice
        display_performance_slow_query_notice = notices.display_performance_slow_query_notice
        display_scale_threshold_notice = notices.display_scale_threshold_notice
        display_temporal_usage_notice = notices.display_temporal_usage_notice

        if notice_type == "temporal":
            display_temporal_usage_notice(memory_instance, sync_type, operation, *notice_args)
        elif notice_type == "scale":
            display_scale_threshold_notice(memory_instance, sync_type, operation, *notice_args)
        elif notice_type == "performance":
            display_performance_slow_query_notice(
                memory_instance, sync_type, operation, *notice_args
            )
        elif notice_type == "decay":
            display_decay_usage_notice(memory_instance, sync_type, operation, *notice_args)
        elif notice_type == "first_run":
            display_first_run_notice(memory_instance, sync_type, operation)

    async def dispatch_notice_async(
        self,
        memory_instance: Any,
        notice_type: str,
        notice_args: tuple,
        sync_type: str,
        operation: str,
    ) -> None:
        import asyncio

        notices = self._get_notice_module()
        display_decay_usage_notice_async = notices.display_decay_usage_notice_async
        display_first_run_notice_async = notices.display_first_run_notice_async
        display_performance_slow_query_notice_async = notices.display_performance_slow_query_notice_async
        display_scale_threshold_notice_async = notices.display_scale_threshold_notice_async
        display_temporal_usage_notice_async = notices.display_temporal_usage_notice_async
        detect_scale_threshold_from_add_result = notices.detect_scale_threshold_from_add_result

        if notice_type == "temporal":
            await display_temporal_usage_notice_async(
                memory_instance, sync_type, operation, *notice_args
            )
        elif notice_type == "scale":
            scale_notice = (
                await asyncio.to_thread(
                    detect_scale_threshold_from_add_result, memory_instance, notice_args
                )
                if isinstance(notice_args, list)
                else notice_args
            )
            if isinstance(notice_args, list):
                await display_scale_threshold_notice_async(
                    memory_instance, sync_type, operation, *scale_notice
                )
            else:
                await display_scale_threshold_notice_async(
                    memory_instance, sync_type, operation, *notice_args
                )
        elif notice_type == "performance":
            await display_performance_slow_query_notice_async(
                memory_instance, sync_type, operation, *notice_args
            )
        elif notice_type == "decay":
            await display_decay_usage_notice_async(
                memory_instance, sync_type, operation, *notice_args
            )
        elif notice_type == "first_run":
            await display_first_run_notice_async(memory_instance, sync_type, operation)


_default_hooks: MemoryHooks = DefaultMemoryHooks()


def get_default_hooks() -> MemoryHooks:
    """Get the global default hooks instance."""
    return _default_hooks


def set_default_hooks(hooks: MemoryHooks) -> None:
    """Set the global default hooks instance (used for testing).

    This allows tests to inject mock hooks without modifying OperationLifecycle
    or creating circular import issues.
    """
    global _default_hooks
    _default_hooks = hooks

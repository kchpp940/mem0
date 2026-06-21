"""
Feedback Middleware.

Responsible for *detecting* and *injecting* feedback / notice state into
the middleware context so that downstream middleware (specifically
:class:`NoticesMiddleware`) can display the appropriate user-facing
notification.

Hook contract
-------------

All hooks are ``after_*`` — feedback detection happens after the core
operation, when the result and elapsed-time data are available.

===========  ===================  ===================================================  ==============================
Phase        Hook                  Effect                                                Reads / Writes
===========  ===================  ===================================================  ==============================
after_add    ``after_add``          Detects temporal usage from metadata,                **Reads**: ``ctx.kwargs["metadata"]``,
             (async too)            scale threshold from add results,                    ``ctx.extras["add_results"]``,
                                    or falls back to first-run.                          ``ctx.extras["vector_store_result"]``
                                                                                         **Writes**: ``ctx.extras["temporal_usage_notice"]``,
                                                                                         ``ctx.extras["scale_threshold_notice"]``,
                                                                                         ``ctx.extras["first_run_notice"]``

after_get    ``after_get``          Falls back to first-run notice.                      **Writes**: ``ctx.extras["first_run_notice"]``
             (async too)

after_get    ``after_get_all``      Detects scale threshold from top_k,                  **Reads**: ``ctx.kwargs["top_k"]``
_all         (async too)            or falls back to first-run.                          **Writes**: ``ctx.extras["scale_threshold_notice"]``,
                                                                                         ``ctx.extras["first_run_notice"]``

after_search ``after_search``        Detects temporal usage from query/filters,           **Reads**: ``ctx.kwargs["query"]``,
             (async too)            scale threshold from top_k,                          ``ctx.kwargs["filters"]``,
                                    slow query from elapsed time,                        ``ctx.kwargs["top_k"]``,
                                    or falls back to first-run.                          ``ctx.extras["search_elapsed_seconds"]``,
                                                                                         ``ctx.extras["search_result_count"]``
                                                                                         **Writes**: ``ctx.extras["temporal_usage_notice"]``,
                                                                                         ``ctx.extras["scale_threshold_notice"]``,
                                                                                         ``ctx.extras["slow_query_notice"]``,
                                                                                         ``ctx.extras["first_run_notice"]``

after_update ``after_update``       Falls back to first-run notice.                      **Writes**: ``ctx.extras["first_run_notice"]``
             (async too)

after_delete ``after_delete``       Detects decay usage, or falls back to first-run.     **Writes**: ``ctx.extras["decay_usage_notice"]``,
             (async too)                                                                 ``ctx.extras["first_run_notice"]``

after_delete ``after_delete_all``   Detects decay usage from deleted count,              **Reads**: ``ctx.extras["deleted_count"]``
_all         (async too)            or falls back to first-run.                          **Writes**: ``ctx.extras["decay_usage_notice"]``,
                                                                                         ``ctx.extras["first_run_notice"]``

after_       ``after_history``      Falls back to first-run notice.                      **Writes**: ``ctx.extras["first_run_notice"]``
history      (async too)

after_reset  ``after_reset``        Falls back to first-run notice.                      **Writes**: ``ctx.extras["first_run_notice"]``
             (async too)
===========  ===================  ===================================================  ==============================

Detection vs. display
---------------------
This separation ensures that *what* to notice is decided here (close to
the data), while *how* to notify the user is decided in
:class:`NoticesMiddleware` (close to the display layer).  FeedbackMiddleware
writes to ``ctx.extras``; NoticesMiddleware reads from it.

Priority order
--------------
When multiple notices could fire, this middleware respects the same
priority as the original inline code: temporal > scale > slow_query >
decay > first_run.
"""

from __future__ import annotations


from mem0.memory.middleware.base import BaseMiddleware, HookContext
from mem0.memory.notices import (
    PERFORMANCE_SLOW_QUERY_THRESHOLD_SECONDS,
    detect_decay_usage_from_delete,
    detect_decay_usage_from_delete_all,
    detect_scale_threshold_from_add_result,
    detect_scale_threshold_from_top_k,
    detect_temporal_usage_from_metadata,
    detect_temporal_usage_from_search,
)


class FeedbackMiddleware(BaseMiddleware):
    name = "feedback"

    # ------------------------------------------------------------------
    # add
    # ------------------------------------------------------------------
    def after_add(self, ctx: HookContext) -> None:
        if ctx.error is not None:
            return
        extras = ctx.extras
        kwargs = ctx.kwargs

        metadata = kwargs.get("metadata") or {}
        temporal_usage_notice = detect_temporal_usage_from_metadata(metadata)
        if temporal_usage_notice:
            extras["temporal_usage_notice"] = temporal_usage_notice
            return

        add_results = extras.get("add_results")
        if add_results is not None:
            scale_threshold_notice = detect_scale_threshold_from_add_result(ctx.memory, add_results)
            if scale_threshold_notice:
                extras["scale_threshold_notice"] = scale_threshold_notice
                return

        vector_store_result = extras.get("vector_store_result")
        if vector_store_result is not None:
            scale_threshold_notice = detect_scale_threshold_from_add_result(ctx.memory, vector_store_result)
            if scale_threshold_notice:
                extras["scale_threshold_notice"] = scale_threshold_notice
                return

        extras["first_run_notice"] = True

    # ------------------------------------------------------------------
    # get
    # ------------------------------------------------------------------
    def after_get(self, ctx: HookContext) -> None:
        if ctx.error is not None:
            return
        ctx.extras["first_run_notice"] = True

    # ------------------------------------------------------------------
    # get_all
    # ------------------------------------------------------------------
    def after_get_all(self, ctx: HookContext) -> None:
        if ctx.error is not None:
            return
        kwargs = ctx.kwargs
        top_k = kwargs.get("top_k", 20)
        scale_threshold_notice = detect_scale_threshold_from_top_k(top_k)
        if scale_threshold_notice:
            ctx.extras["scale_threshold_notice"] = scale_threshold_notice
        else:
            ctx.extras["first_run_notice"] = True

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------
    def after_search(self, ctx: HookContext) -> None:
        if ctx.error is not None:
            return
        extras = ctx.extras
        kwargs = ctx.kwargs

        query = kwargs.get("query", "")
        filters = kwargs.get("filters")
        temporal_usage_notice = detect_temporal_usage_from_search(query, filters)
        if temporal_usage_notice:
            extras["temporal_usage_notice"] = temporal_usage_notice
            return

        top_k = kwargs.get("top_k", 20)
        scale_threshold_notice = detect_scale_threshold_from_top_k(top_k)
        if scale_threshold_notice:
            extras["scale_threshold_notice"] = scale_threshold_notice
            return

        search_elapsed_seconds = extras.get("search_elapsed_seconds", 0.0)
        result_count = extras.get("search_result_count", 0)
        if search_elapsed_seconds > PERFORMANCE_SLOW_QUERY_THRESHOLD_SECONDS:
            extras["slow_query_notice"] = (search_elapsed_seconds, top_k, result_count)
            return

        extras["first_run_notice"] = True

    # ------------------------------------------------------------------
    # update
    # ------------------------------------------------------------------
    def after_update(self, ctx: HookContext) -> None:
        if ctx.error is not None:
            return
        ctx.extras["first_run_notice"] = True

    # ------------------------------------------------------------------
    # delete
    # ------------------------------------------------------------------
    def after_delete(self, ctx: HookContext) -> None:
        if ctx.error is not None:
            return
        decay_usage_notice = detect_decay_usage_from_delete()
        if decay_usage_notice:
            ctx.extras["decay_usage_notice"] = decay_usage_notice
        else:
            ctx.extras["first_run_notice"] = True

    # ------------------------------------------------------------------
    # delete_all
    # ------------------------------------------------------------------
    def after_delete_all(self, ctx: HookContext) -> None:
        if ctx.error is not None:
            return
        deleted_count = ctx.extras.get("deleted_count", 0)
        decay_usage_notice = detect_decay_usage_from_delete_all(deleted_count)
        if decay_usage_notice:
            ctx.extras["decay_usage_notice"] = decay_usage_notice
        else:
            ctx.extras["first_run_notice"] = True

    # ------------------------------------------------------------------
    # history / reset
    # ------------------------------------------------------------------
    def after_history(self, ctx: HookContext) -> None:
        if ctx.error is not None:
            return
        ctx.extras["first_run_notice"] = True

    def after_reset(self, ctx: HookContext) -> None:
        if ctx.error is not None:
            return
        ctx.extras["first_run_notice"] = True

    # ------------------------------------------------------------------
    # async variants
    # ------------------------------------------------------------------
    async def after_add_async(self, ctx: HookContext) -> None:
        import asyncio

        await asyncio.to_thread(self.after_add, ctx)

    async def after_get_async(self, ctx: HookContext) -> None:
        import asyncio

        await asyncio.to_thread(self.after_get, ctx)

    async def after_get_all_async(self, ctx: HookContext) -> None:
        import asyncio

        await asyncio.to_thread(self.after_get_all, ctx)

    async def after_search_async(self, ctx: HookContext) -> None:
        import asyncio

        await asyncio.to_thread(self.after_search, ctx)

    async def after_update_async(self, ctx: HookContext) -> None:
        import asyncio

        await asyncio.to_thread(self.after_update, ctx)

    async def after_delete_async(self, ctx: HookContext) -> None:
        import asyncio

        await asyncio.to_thread(self.after_delete, ctx)

    async def after_delete_all_async(self, ctx: HookContext) -> None:
        import asyncio

        await asyncio.to_thread(self.after_delete_all, ctx)

    async def after_history_async(self, ctx: HookContext) -> None:
        import asyncio

        await asyncio.to_thread(self.after_history, ctx)

    async def after_reset_async(self, ctx: HookContext) -> None:
        import asyncio

        await asyncio.to_thread(self.after_reset, ctx)

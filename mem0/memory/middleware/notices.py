"""
Notices Middleware.

Handles the display of best-effort user-facing notices:

* First-run notice
* Temporal usage notice
* Scale threshold notice
* Decay usage notice
* Performance slow-query notice

The actual notice implementation lives in :mod:`mem0.memory.notices`.  The core
Memory methods no longer decide *when* to display notices; instead they simply
stash pre-computed detection results on ``ctx.extras`` under well-known keys
and this middleware dispatches to the right notice function in the appropriate
``after_*`` hook.

If no notice flag is set on ``ctx.extras`` we fall back to the generic
``display_first_run_notice`` call (the original default behaviour.

This middleware also owns the *display logic and order of precedence: temporal >
scale > slow-query > first-run for every operation — exactly the same order
as the inline ``if/elif/elif/else`` ladder previously embedded in each memory method.
"""

from __future__ import annotations


from mem0.memory.middleware.base import BaseMiddleware, HookContext
from mem0.memory.notices import (
    display_decay_usage_notice,
    display_first_run_notice,
    display_performance_slow_query_notice,
    display_scale_threshold_notice,
    display_temporal_usage_notice,
)


class NoticesMiddleware(BaseMiddleware):
    name = "notices"

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _sync_type(ctx: HookContext) -> str:
        from mem0.memory.main import AsyncMemory

        if isinstance(ctx.memory, AsyncMemory):
            return "async"
        return "sync"

    @classmethod
    def _dispatch(cls, ctx: HookContext, operation: str) -> None:
        """Display the appropriate notice based on ctx.extras flags.

        Expects zero or more of these keys to be set on ctx.extras:

        * ``temporal_usage_notice``  – tuple passed to
          ``display_temporal_usage_notice``
        * ``scale_threshold_notice``  – tuple passed to
          ``display_scale_threshold_notice``
        * ``decay_usage_notice``  – tuple passed to
          ``display_decay_usage_notice``
        * ``slow_query``  – a dict ``{"elapsed_seconds": float,
          "top_k": int, "result_count": int}``
          passed to ``display_performance_slow_query_notice``

        If none are set, ``display_first_run_notice`` is called as the
        fallback — matching the original else-branch behaviour.
        """
        if ctx.error is not None:
            return

        memory = ctx.memory
        sync_type = cls._sync_type(ctx)
        extras = ctx.extras

        if "temporal_usage_notice" in extras:
            display_temporal_usage_notice(
                memory, sync_type, operation, *extras["temporal_usage_notice"]
            )
        elif "scale_threshold_notice" in extras:
            display_scale_threshold_notice(
                memory, sync_type, operation, *extras["scale_threshold_notice"]
            )
        elif "slow_query" in extras:
            sq = extras["slow_query"]
            display_performance_slow_query_notice(
                memory,
                sync_type,
                operation,
                sq["elapsed_seconds"],
                sq["top_k"],
                sq["result_count"],
            )
        elif "decay_usage_notice" in extras:
            display_decay_usage_notice(
                memory, sync_type, operation, *extras["decay_usage_notice"]
            )
        else:
            display_first_run_notice(memory, sync_type, operation)

    # ------------------------------------------------------------------
    # after hooks — dispatch per operation
    # ------------------------------------------------------------------
    def after_add(self, ctx: HookContext) -> None:
        self._dispatch(ctx, "add")

    def after_get(self, ctx: HookContext) -> None:
        self._dispatch(ctx, "get")

    def after_get_all(self, ctx: HookContext) -> None:
        self._dispatch(ctx, "get_all")

    def after_search(self, ctx: HookContext) -> None:
        self._dispatch(ctx, "search")

    def after_update(self, ctx: HookContext) -> None:
        self._dispatch(ctx, "update")

    def after_delete(self, ctx: HookContext) -> None:
        self._dispatch(ctx, "delete")

    def after_delete_all(self, ctx: HookContext) -> None:
        self._dispatch(ctx, "delete_all")

    def after_history(self, ctx: HookContext) -> None:
        self._dispatch(ctx, "history")

    def after_reset(self, ctx: HookContext) -> None:
        self._dispatch(ctx, "reset")

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

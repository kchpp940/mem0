"""
Telemetry Middleware.

Captures anonymous telemetry events (operation traces) for every memory
operation via the existing ``capture_event`` helper.  The actual
PostHog-backed implementation lives in :mod:`mem0.memory.telemetry`.

Hook contract
-------------

All hooks are ``after_*`` — telemetry is emitted *after* the core
operation completes.  Every operation fires a ``mem0.<op>`` event.

===========  ===================  ===================================================  ==============================
Phase        Hook                  Event name                                          Reads / Writes
===========  ===================  ===================================================  ==============================
after_add    ``after_add``          ``mem0.add``                                        **Reads**: ``ctx.extras["keys"]``,
             (async too)                                                                ``ctx.extras["encoded_ids"]``,
                                                                                        ``ctx.memory.api_version``

after_get    ``after_get``          ``mem0.get``                                        **Reads**: ``ctx.kwargs["memory_id"]``

after_get    ``after_get_all``      ``mem0.get_all``                                    **Reads**: ``ctx.kwargs["top_k"]``,
_all         (async too)                                                                ``ctx.extras["keys"]``,
                                                                                        ``ctx.extras["encoded_ids"]``

after_search ``after_search``        ``mem0.search``                                    **Reads**: ``ctx.kwargs["top_k"]``,
             (async too)                                                                ``ctx.kwargs["threshold"]``,
                                                                                        ``ctx.kwargs["explain"]``,
                                                                                        ``ctx.kwargs["advanced_filters"]``,
                                                                                        ``ctx.extras["keys"]``,
                                                                                        ``ctx.extras["encoded_ids"]``,
                                                                                        ``ctx.memory.api_version``

after_update ``after_update``        ``mem0.update``                                    **Reads**: ``ctx.kwargs["memory_id"]``

after_delete ``after_delete``        ``mem0.delete``                                    **Reads**: ``ctx.kwargs["memory_id"]``

after_delete ``after_delete_all``    ``mem0.delete_all``                                **Reads**: ``ctx.extras["keys"]``,
_all         (async too)                                                                ``ctx.extras["encoded_ids"]``

after_       ``after_history``       ``mem0.history``                                   **Reads**: ``ctx.kwargs["memory_id"]``
history      (async too)

after_reset  ``after_reset``         ``mem0.reset``                                     (no extra data)
             (async too)
===========  ===================  ===================================================  ==============================

Best-effort
-----------
This middleware is **best-effort** (``critical = False``).  If
``capture_event`` raises, the error is logged at WARNING level and
skipped — it never interrupts the operation.
"""

from __future__ import annotations


from mem0.memory.middleware.base import BaseMiddleware, HookContext
from mem0.memory.telemetry import capture_event


class TelemetryMiddleware(BaseMiddleware):
    name = "telemetry"

    # ------------------------------------------------------------------
    # sync hooks — every operation fires a mem0.<op> event in the after hook
    # ------------------------------------------------------------------
    def _sync_type(self, ctx: HookContext) -> str:
        from mem0.memory.main import AsyncMemory

        if isinstance(ctx.memory, AsyncMemory):
            return "async"
        return "sync"

    def after_add(self, ctx: HookContext) -> None:
        data = {"version": ctx.memory.api_version, "sync_type": self._sync_type(ctx)}
        extras = ctx.extras
        if "keys" in extras:
            data["keys"] = extras["keys"]
        if "encoded_ids" in extras:
            data["encoded_ids"] = extras["encoded_ids"]
        capture_event("mem0.add", ctx.memory, data)

    def after_get(self, ctx: HookContext) -> None:
        capture_event(
            "mem0.get",
            ctx.memory,
            {
                "memory_id": ctx.kwargs.get("memory_id"),
                "sync_type": self._sync_type(ctx),
            },
        )

    def after_get_all(self, ctx: HookContext) -> None:
        data = {
            "limit": ctx.kwargs.get("top_k", 20),
            "sync_type": self._sync_type(ctx),
        }
        if "keys" in ctx.extras:
            data["keys"] = ctx.extras["keys"]
        if "encoded_ids" in ctx.extras:
            data["encoded_ids"] = ctx.extras["encoded_ids"]
        capture_event("mem0.get_all", ctx.memory, data)

    def after_search(self, ctx: HookContext) -> None:
        data = {
            "limit": ctx.kwargs.get("top_k", 20),
            "version": ctx.memory.api_version,
            "sync_type": self._sync_type(ctx),
            "threshold": ctx.kwargs.get("threshold", 0.1),
            "explain": ctx.kwargs.get("explain", False),
            "advanced_filters": bool(ctx.kwargs.get("advanced_filters", False)),
        }
        if "keys" in ctx.extras:
            data["keys"] = ctx.extras["keys"]
        if "encoded_ids" in ctx.extras:
            data["encoded_ids"] = ctx.extras["encoded_ids"]
        capture_event("mem0.search", ctx.memory, data)

    def after_update(self, ctx: HookContext) -> None:
        capture_event(
            "mem0.update",
            ctx.memory,
            {
                "memory_id": ctx.kwargs.get("memory_id"),
                "sync_type": self._sync_type(ctx),
            },
        )

    def after_delete(self, ctx: HookContext) -> None:
        capture_event(
            "mem0.delete",
            ctx.memory,
            {
                "memory_id": ctx.kwargs.get("memory_id"),
                "sync_type": self._sync_type(ctx),
            },
        )

    def after_delete_all(self, ctx: HookContext) -> None:
        data = {"sync_type": self._sync_type(ctx)}
        if "keys" in ctx.extras:
            data["keys"] = ctx.extras["keys"]
        if "encoded_ids" in ctx.extras:
            data["encoded_ids"] = ctx.extras["encoded_ids"]
        capture_event("mem0.delete_all", ctx.memory, data)

    def after_history(self, ctx: HookContext) -> None:
        capture_event(
            "mem0.history",
            ctx.memory,
            {
                "memory_id": ctx.kwargs.get("memory_id"),
                "sync_type": self._sync_type(ctx),
            },
        )

    def after_reset(self, ctx: HookContext) -> None:
        capture_event(
            "mem0.reset",
            ctx.memory,
            {
                "sync_type": self._sync_type(ctx),
            },
        )

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

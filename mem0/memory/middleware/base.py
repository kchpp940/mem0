"""
Memory Middleware Framework.

Provides a unified hook-based mechanism for attaching side-effects
(trace/telemetry, lifecycle annotations, history recording, notices, etc.)
to the core Memory operation pipeline (add, search, get, get_all,
update, delete, delete_all, history) without polluting the main flow.

Hook execution order
--------------------

For a successful operation:

    1. middleware.before_<op>(ctx)          # all middleware, registration order
    2. <core operation runs>                # ctx.result / ctx.error populated
    3. middleware.after_<op>(ctx)           # all middleware, registration order

If an error is raised during the core operation:

    1. middleware.before_<op>(ctx)          # those that already ran stay ran
    2. <core operation raises>              # ctx.error is set
    3. middleware.after_<op>(ctx)           # *still* runs for every middleware,
                                             # middleware can inspect ctx.error

Each hook receives a mutable ``HookContext`` and may mutate it in place
(eg. inject extra metadata in ``before_add`` or annotate results in
``after_search``).  Hooks MUST NOT raise — any exception is swallowed at
the manager level so a broken middleware can never break the main flow.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

MEMORY_OPERATIONS = frozenset(
    {
        "add",
        "search",
        "get",
        "get_all",
        "update",
        "delete",
        "delete_all",
        "history",
        "reset",
    }
)


@dataclass
class HookContext:
    """Shared context object threaded through every middleware hook.

    Attributes
    ----------
    operation:
        Name of the memory operation being performed (e.g. ``"add"``).
    memory:
        The owning ``Memory`` / ``AsyncMemory`` instance.  Hooks can use
        this to reach config, vector store, db, etc.
    kwargs:
        Keyword arguments originally passed to the operation.  Mutable so
        ``before_*`` hooks can normalise or inject values (e.g. add
        ``expires_at`` to metadata).
    result:
        Return value produced by the core operation.  Only populated in
        ``after_*`` hooks (and only when no error occurred).  Mutable so
        hooks can annotate / enrich the result before it reaches the
        caller.
    error:
        Exception raised by the core operation (or ``None``).
    extras:
        Free-form dictionary for passing ad-hoc data between hooks of
        different middleware (e.g. a telemetry start timestamp, a
        pre-computed notice detection flag, etc.).
    """

    operation: str
    memory: Any
    kwargs: Dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: Optional[BaseException] = None
    extras: Dict[str, Any] = field(default_factory=dict)


class BaseMiddleware:
    """Base class for memory middleware.

    Subclass and override any subset of the ``before_*`` / ``after_*``
    hooks you care about.  Default implementations are no-ops so you
    only need to implement the hooks relevant to your concern.

    All hooks receive a single :class:`HookContext` argument and must
    never raise — any exception will be caught and logged by the
    :class:`MiddlewareManager` so one misbehaving middleware cannot
    take down the whole pipeline.

    Naming convention
    -----------------
    Hooks follow the pattern::

        before_<operation>(ctx: HookContext) -> None
        after_<operation>(ctx: HookContext) -> None

    where ``<operation>`` is one of the values in
    :data:`MEMORY_OPERATIONS`.

    Async middleware
    ----------------
    The same class is used for both sync and async pipelines.  For
    :class:`AsyncMemory` the manager additionally looks for hooks named
    ``before_<operation>_async`` / ``after_<operation>_async`` and
    awaits those instead of the sync variants when present.  If no async
    variant is defined the sync hook is wrapped with
    ``asyncio.to_thread`` automatically.
    """

    name: str = "base"

    # ------------------------------------------------------------------
    # add
    # ------------------------------------------------------------------
    def before_add(self, ctx: HookContext) -> None:
        ...

    def after_add(self, ctx: HookContext) -> None:
        ...

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------
    def before_search(self, ctx: HookContext) -> None:
        ...

    def after_search(self, ctx: HookContext) -> None:
        ...

    # ------------------------------------------------------------------
    # get
    # ------------------------------------------------------------------
    def before_get(self, ctx: HookContext) -> None:
        ...

    def after_get(self, ctx: HookContext) -> None:
        ...

    # ------------------------------------------------------------------
    # get_all
    # ------------------------------------------------------------------
    def before_get_all(self, ctx: HookContext) -> None:
        ...

    def after_get_all(self, ctx: HookContext) -> None:
        ...

    # ------------------------------------------------------------------
    # update
    # ------------------------------------------------------------------
    def before_update(self, ctx: HookContext) -> None:
        ...

    def after_update(self, ctx: HookContext) -> None:
        ...

    # ------------------------------------------------------------------
    # delete
    # ------------------------------------------------------------------
    def before_delete(self, ctx: HookContext) -> None:
        ...

    def after_delete(self, ctx: HookContext) -> None:
        ...

    # ------------------------------------------------------------------
    # delete_all
    # ------------------------------------------------------------------
    def before_delete_all(self, ctx: HookContext) -> None:
        ...

    def after_delete_all(self, ctx: HookContext) -> None:
        ...

    # ------------------------------------------------------------------
    # history
    # ------------------------------------------------------------------
    def before_history(self, ctx: HookContext) -> None:
        ...

    def after_history(self, ctx: HookContext) -> None:
        ...

    # ------------------------------------------------------------------
    # reset
    # ------------------------------------------------------------------
    def before_reset(self, ctx: HookContext) -> None:
        ...

    def after_reset(self, ctx: HookContext) -> None:
        ...


class MiddlewareManager:
    """Orchestrates middleware execution around a core operation.

    Usage (sync)::

        ctx = HookContext(operation="add", memory=self, kwargs=locals())
        with manager.run(ctx):
            ctx.result = self._actual_add(**ctx.kwargs)
        return ctx.result

    Usage (async)::

        ctx = HookContext(operation="search", memory=self, kwargs=locals())
        async with manager.run_async(ctx):
            ctx.result = await self._actual_search(**ctx.kwargs)
        return ctx.result
    """

    def __init__(self, middleware: Optional[List[BaseMiddleware]] = None):
        self._middleware: List[BaseMiddleware] = list(middleware or [])

    # ------------------------------------------------------------------
    # registration
    # ------------------------------------------------------------------
    def add(self, middleware: BaseMiddleware) -> None:
        """Append a middleware to the execution chain."""
        if not isinstance(middleware, BaseMiddleware):
            raise TypeError(
                f"middleware must inherit from BaseMiddleware, got {type(middleware).__name__}"
            )
        self._middleware.append(middleware)

    def add_many(self, middleware_list: List[BaseMiddleware]) -> None:
        for m in middleware_list:
            self.add(m)

    @property
    def middleware(self) -> List[BaseMiddleware]:
        return list(self._middleware)

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------
    def _validate_operation(self, operation: str) -> None:
        if operation not in MEMORY_OPERATIONS:
            raise ValueError(
                f"Unknown memory operation {operation!r}. "
                f"Expected one of {sorted(MEMORY_OPERATIONS)}."
            )

    @staticmethod
    def _safe_call(fn: Callable[[HookContext], None], ctx: HookContext, name: str) -> None:
        try:
            fn(ctx)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Middleware hook %s raised %s: %s. Hook has been skipped.",
                name,
                type(exc).__name__,
                exc,
            )

    @staticmethod
    async def _safe_call_async(
        fn: Callable[[HookContext], Awaitable[None]],
        ctx: HookContext,
        name: str,
    ) -> None:
        try:
            await fn(ctx)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Middleware hook %s raised %s: %s. Hook has been skipped.",
                name,
                type(exc).__name__,
                exc,
            )

    # ------------------------------------------------------------------
    # sync runner
    # ------------------------------------------------------------------
    def run(self, ctx: HookContext) -> "_SyncCtxManager":
        """Return a context manager that runs before/after hooks.

        The yielded context manager runs ``before_<op>`` on ``__enter__``
        and ``after_<op>`` on ``__exit__`` (guaranteed, even if the body
        raises).
        """
        self._validate_operation(ctx.operation)
        return _SyncCtxManager(self, ctx)

    # ------------------------------------------------------------------
    # async runner
    # ------------------------------------------------------------------
    def run_async(self, ctx: HookContext) -> "_AsyncCtxManager":
        """Async variant of :meth:`run`."""
        self._validate_operation(ctx.operation)
        return _AsyncCtxManager(self, ctx)


# ---------------------------------------------------------------------------
# Context managers returned by MiddlewareManager
# ---------------------------------------------------------------------------


class _SyncCtxManager:
    def __init__(self, manager: MiddlewareManager, ctx: HookContext):
        self._manager = manager
        self._ctx = ctx

    def __enter__(self) -> HookContext:
        op = self._ctx.operation
        hook_name = f"before_{op}"
        for mw in self._manager._middleware:
            fn = getattr(mw, hook_name, None)
            if callable(fn):
                MiddlewareManager._safe_call(fn, self._ctx, f"{mw.name}.{hook_name}")
        return self._ctx

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_val is not None:
            self._ctx.error = exc_val
        op = self._ctx.operation
        hook_name = f"after_{op}"
        for mw in self._manager._middleware:
            fn = getattr(mw, hook_name, None)
            if callable(fn):
                MiddlewareManager._safe_call(fn, self._ctx, f"{mw.name}.{hook_name}")
        # Do not suppress exceptions raised by the core operation.
        return None


class _AsyncCtxManager:
    def __init__(self, manager: MiddlewareManager, ctx: HookContext):
        self._manager = manager
        self._ctx = ctx

    async def __aenter__(self) -> HookContext:
        import asyncio

        op = self._ctx.operation
        async_hook = f"before_{op}_async"
        sync_hook = f"before_{op}"
        for mw in self._manager._middleware:
            if hasattr(mw, async_hook) and callable(getattr(mw, async_hook)):
                await MiddlewareManager._safe_call_async(
                    getattr(mw, async_hook), self._ctx, f"{mw.name}.{async_hook}"
                )
            else:
                fn = getattr(mw, sync_hook, None)
                if callable(fn):
                    await asyncio.to_thread(
                        MiddlewareManager._safe_call, fn, self._ctx, f"{mw.name}.{sync_hook}"
                    )
        return self._ctx

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        import asyncio

        if exc_val is not None:
            self._ctx.error = exc_val
        op = self._ctx.operation
        async_hook = f"after_{op}_async"
        sync_hook = f"after_{op}"
        for mw in self._manager._middleware:
            if hasattr(mw, async_hook) and callable(getattr(mw, async_hook)):
                await MiddlewareManager._safe_call_async(
                    getattr(mw, async_hook), self._ctx, f"{mw.name}.{async_hook}"
                )
            else:
                fn = getattr(mw, sync_hook, None)
                if callable(fn):
                    await asyncio.to_thread(
                        MiddlewareManager._safe_call, fn, self._ctx, f"{mw.name}.{sync_hook}"
                    )
        return None

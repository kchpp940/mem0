"""
Memory Middleware Framework.

Provides a unified hook-based mechanism for attaching side-effects
(trace/telemetry, lifecycle annotations, history recording, notices, etc.)
to the core Memory operation pipeline (add, search, get, get_all,
update, delete, delete_all, history, reset) without polluting the main flow.

Hook execution order
--------------------

For a successful operation:

    1. middleware.before_<op>(ctx)          # *all* middleware, registration order
    2. <core operation runs>                # ctx.result / ctx.error populated
    3. [Phase 1] critical after-hooks       # all critical middleware, registration order
    4. [Phase 2] best-effort after-hooks    # only if Phase 1 succeeded; registration order

If an error is raised during the core operation:

    1. middleware.before_<op>(ctx)          # those that already ran stay ran
    2. <core operation raises>              # ctx.error is set
    3. [Phase 1] critical after-hooks       # still run (every critical middleware
                                             # gets a chance to clean up or observe)
    4. [Phase 2] skipped if Phase 1 failed

If a *critical* after-hook fails, Phase 2 is **not executed**.  This
guarantees that "success-reporting" side-effects (telemetry events, user
notices) never fire when a required side-effect (e.g. history
persistence) did not land — preventing the contradictory state where
the caller sees an error but telemetry has already emitted a success
event.

Each hook receives a mutable :class:`HookContext` and may mutate it in place
(eg. inject extra metadata in ``before_add`` or annotate results in
``after_search``).

Error propagation
-----------------

Each middleware declares whether it is **critical** (``critical = True``) or
best-effort (the default).

* **Best-effort** middleware hooks that raise are logged at ``WARNING`` level
  and skipped.  The operation continues normally and the caller never sees
  the exception.

* **Critical** middleware hooks that raise are logged at ``ERROR`` level and
  recorded on ``ctx.hook_errors``.  After all *critical* after-hooks have
  run the manager raises a single :class:`MiddlewareError` that aggregates
  every critical failure.  This ensures:

  - Every critical middleware still gets a chance to run (one broken hook
    does not prevent others from executing).
  - The caller is guaranteed to know when a required side-effect failed.
  - Best-effort side-effects are skipped so success semantics stay
    consistent.
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
class HookError:
    """Record of a single hook failure.

    Attributes
    ----------
    middleware_name:
        ``name`` attribute of the middleware that raised.
    hook_name:
        Fully qualified hook name (e.g. ``"history.after_add"``).
    exception:
        The exception that was raised.
    critical:
        Whether the middleware is marked as critical.
    """

    middleware_name: str
    hook_name: str
    exception: BaseException
    critical: bool


class MiddlewareError(Exception):
    """Raised after all hooks have executed when one or more *critical*
    middleware hooks failed.

    The ``errors`` attribute contains the full list of :class:`HookError`
    records so callers can inspect which hooks failed and why.
    """

    def __init__(self, errors: List[HookError]):
        self.errors = errors
        names = ", ".join(f"{e.hook_name} ({type(e.exception).__name__})" for e in errors)
        super().__init__(f"Critical middleware hook(s) failed: {names}")


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
    hook_errors:
        List of :class:`HookError` records collected during hook
        execution.  Populated by the :class:`MiddlewareManager` when a
        hook raises.
    """

    operation: str
    memory: Any
    kwargs: Dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: Optional[BaseException] = None
    extras: Dict[str, Any] = field(default_factory=dict)
    hook_errors: List[HookError] = field(default_factory=list)


class BaseMiddleware:
    """Base class for memory middleware.

    Subclass and override any subset of the ``before_*`` / ``after_*``
    hooks you care about.  Default implementations are no-ops so you
    only need to implement the hooks relevant to your concern.

    Error propagation
    -----------------
    Set the ``critical`` class attribute to ``True`` when the middleware
    implements a side-effect that *must not* fail silently (e.g. history
    persistence).  If a critical hook raises, the error is recorded on
    ``ctx.hook_errors`` and, after all hooks have run, a
    :class:`MiddlewareError` is raised to notify the caller.

    For best-effort middleware (``critical = False``, the default), any
    exception is logged at ``WARNING`` level and swallowed so the
    operation continues normally.

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
    critical: bool = False

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
    def _call_hook(
        fn: Callable[[HookContext], None],
        ctx: HookContext,
        hook_name: str,
        middleware_name: str,
        critical: bool,
    ) -> None:
        try:
            fn(ctx)
        except Exception as exc:
            hook_err = HookError(
                middleware_name=middleware_name,
                hook_name=hook_name,
                exception=exc,
                critical=critical,
            )
            ctx.hook_errors.append(hook_err)
            if critical:
                logger.error(
                    "Critical middleware hook %s raised %s: %s.",
                    hook_name,
                    type(exc).__name__,
                    exc,
                )
            else:
                logger.warning(
                    "Best-effort middleware hook %s raised %s: %s. Hook has been skipped.",
                    hook_name,
                    type(exc).__name__,
                    exc,
                )

    @staticmethod
    async def _call_hook_async(
        fn: Callable[[HookContext], Awaitable[None]],
        ctx: HookContext,
        hook_name: str,
        middleware_name: str,
        critical: bool,
    ) -> None:
        try:
            await fn(ctx)
        except Exception as exc:
            hook_err = HookError(
                middleware_name=middleware_name,
                hook_name=hook_name,
                exception=exc,
                critical=critical,
            )
            ctx.hook_errors.append(hook_err)
            if critical:
                logger.error(
                    "Critical middleware hook %s raised %s: %s.",
                    hook_name,
                    type(exc).__name__,
                    exc,
                )
            else:
                logger.warning(
                    "Best-effort middleware hook %s raised %s: %s. Hook has been skipped.",
                    hook_name,
                    type(exc).__name__,
                    exc,
                )

    @staticmethod
    def _raise_if_critical_errors(ctx: HookContext) -> None:
        critical_errors = [e for e in ctx.hook_errors if e.critical]
        if critical_errors:
            raise MiddlewareError(critical_errors)

    # ------------------------------------------------------------------
    # sync runner
    # ------------------------------------------------------------------
    def run(self, ctx: HookContext) -> "_SyncCtxManager":
        """Return a context manager that runs before/after hooks.

        The yielded context manager runs ``before_<op>`` on ``__enter__``
        and ``after_<op>`` on ``__exit__`` (guaranteed, even if the body
        raises).

        If any *critical* middleware hook raises, a
        :class:`MiddlewareError` is raised after all hooks have executed.
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
                MiddlewareManager._call_hook(
                    fn, self._ctx, f"{mw.name}.{hook_name}", mw.name, mw.critical
                )
        MiddlewareManager._raise_if_critical_errors(self._ctx)
        return self._ctx

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_val is not None:
            self._ctx.error = exc_val
        op = self._ctx.operation
        hook_name = f"after_{op}"
        all_mw = self._manager._middleware

        # ---- Phase 1: critical middleware ----
        # Run critical after-hooks first.  If any of them fails we skip the
        # best-effort phase entirely so that "success" side-effects
        # (telemetry, user notices) never fire when a required side-effect
        # (e.g. history persistence) did not land.
        critical_mw = [mw for mw in all_mw if mw.critical]
        for mw in critical_mw:
            fn = getattr(mw, hook_name, None)
            if callable(fn):
                MiddlewareManager._call_hook(
                    fn, self._ctx, f"{mw.name}.{hook_name}", mw.name, mw.critical
                )
        critical_errors = [e for e in self._ctx.hook_errors if e.critical]
        if critical_errors:
            MiddlewareManager._raise_if_critical_errors(self._ctx)
            return None

        # ---- Phase 2: best-effort middleware ----
        # These only run when every critical after-hook succeeded, and their
        # own failures are swallowed (logged as warnings) so they never
        # break the caller.
        best_effort_mw = [mw for mw in all_mw if not mw.critical]
        for mw in best_effort_mw:
            fn = getattr(mw, hook_name, None)
            if callable(fn):
                MiddlewareManager._call_hook(
                    fn, self._ctx, f"{mw.name}.{hook_name}", mw.name, mw.critical
                )
        MiddlewareManager._raise_if_critical_errors(self._ctx)
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
                await MiddlewareManager._call_hook_async(
                    getattr(mw, async_hook),
                    self._ctx,
                    f"{mw.name}.{async_hook}",
                    mw.name,
                    mw.critical,
                )
            else:
                fn = getattr(mw, sync_hook, None)
                if callable(fn):
                    await asyncio.to_thread(
                        MiddlewareManager._call_hook,
                        fn,
                        self._ctx,
                        f"{mw.name}.{sync_hook}",
                        mw.name,
                        mw.critical,
                    )
        MiddlewareManager._raise_if_critical_errors(self._ctx)
        return self._ctx

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        import asyncio

        if exc_val is not None:
            self._ctx.error = exc_val
        op = self._ctx.operation
        async_hook = f"after_{op}_async"
        sync_hook = f"after_{op}"
        all_mw = self._manager._middleware

        # ---- Phase 1: critical middleware ----
        critical_mw = [mw for mw in all_mw if mw.critical]
        for mw in critical_mw:
            if hasattr(mw, async_hook) and callable(getattr(mw, async_hook)):
                await MiddlewareManager._call_hook_async(
                    getattr(mw, async_hook),
                    self._ctx,
                    f"{mw.name}.{async_hook}",
                    mw.name,
                    mw.critical,
                )
            else:
                fn = getattr(mw, sync_hook, None)
                if callable(fn):
                    await asyncio.to_thread(
                        MiddlewareManager._call_hook,
                        fn,
                        self._ctx,
                        f"{mw.name}.{sync_hook}",
                        mw.name,
                        mw.critical,
                    )
        critical_errors = [e for e in self._ctx.hook_errors if e.critical]
        if critical_errors:
            MiddlewareManager._raise_if_critical_errors(self._ctx)
            return None

        # ---- Phase 2: best-effort middleware ----
        best_effort_mw = [mw for mw in all_mw if not mw.critical]
        for mw in best_effort_mw:
            if hasattr(mw, async_hook) and callable(getattr(mw, async_hook)):
                await MiddlewareManager._call_hook_async(
                    getattr(mw, async_hook),
                    self._ctx,
                    f"{mw.name}.{async_hook}",
                    mw.name,
                    mw.critical,
                )
            else:
                fn = getattr(mw, sync_hook, None)
                if callable(fn):
                    await asyncio.to_thread(
                        MiddlewareManager._call_hook,
                        fn,
                        self._ctx,
                        f"{mw.name}.{sync_hook}",
                        mw.name,
                        mw.critical,
                    )
        MiddlewareManager._raise_if_critical_errors(self._ctx)
        return None

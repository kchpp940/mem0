"""
Lifecycle Middleware.

Handles TTL / lifecycle concerns for memory records.

Hook contract
-------------

=========  ============  ===================================================  ======================
Phase      Hook          Effect                                                Reads / Writes
=========  ============  ===================================================  ======================
before_add ``before_add``  Resolves effective ``expires_at`` / ``ttl_source``  **Reads**: ``ctx.kwargs["expires"]``,
           (async too)    from request params + configured policies,           ``ctx.kwargs["ttl_days"]``,
                          then injects into ``kwargs["metadata"]``.            ``ctx.memory.config.lifecycle_policies``
                                                                               **Writes**: ``ctx.kwargs["metadata"]["expires_at"]``,
                                                                               ``ctx.kwargs["metadata"]["ttl_source"]``,
                                                                               ``ctx.extras["expires_at"]``,
                                                                               ``ctx.extras["ttl_source"]``

after_get  ``after_get``  Annotates the single returned memory dict with       **Reads**: ``ctx.result`` (dict)
           (async too)    computed ``ttl_state`` / normalised ``expires_at``   **Writes**: ``ctx.result["expires_at"]``,
                          / defaulted ``ttl_source``.                          ``ctx.result["ttl_state"]``,
                                                                               ``ctx.result["ttl_source"]``

after_get  ``after_get_   Same as after_get but iterates over ``results``      **Reads**: ``ctx.result["results"]``
_all       all``          list in the return dict.                              **Writes**: each item dict (same keys)

after_     ``after_       Same as after_get_all.                                **Reads**: ``ctx.result["results"]``
search     search``                                                             **Writes**: each item dict (same keys)
=========  ============  ===================================================  ======================

All logic is delegated to the existing helpers in
:mod:`mem0.memory.lifecycle` so this middleware is a pure
"wiring" layer — no policy logic is duplicated here.
"""

from __future__ import annotations

from copy import deepcopy

from mem0.memory.lifecycle import (
    LifecyclePolicy,
    annotate_memory_result,
    resolve_expiration,
)
from mem0.memory.middleware.base import BaseMiddleware, HookContext


class LifecycleMiddleware(BaseMiddleware):
    name = "lifecycle"

    # ------------------------------------------------------------------
    # before_add — resolve expiration and inject into metadata
    # ------------------------------------------------------------------
    def before_add(self, ctx: HookContext) -> None:
        kwargs = ctx.kwargs
        lifecycle_cfg = getattr(ctx.memory.config, "lifecycle_policies", None)
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
            request_expires=kwargs.get("expires"),
            request_ttl_days=kwargs.get("ttl_days"),
            workspace_policy=workspace_policy,
            default_policy=default_policy,
        )

        if effective_expires_at is not None:
            metadata = kwargs.get("metadata")
            if metadata is None:
                metadata = {}
            else:
                metadata = deepcopy(metadata)
            metadata["expires_at"] = effective_expires_at
            metadata["ttl_source"] = effective_ttl_source.value
            kwargs["metadata"] = metadata

        # Also stash on extras so downstream code (if any) can reach them
        # directly without re-parsing metadata.
        ctx.extras["expires_at"] = effective_expires_at
        ctx.extras["ttl_source"] = effective_ttl_source.value

    # ------------------------------------------------------------------
    # after_<read> — annotate returned memory payloads
    # ------------------------------------------------------------------
    def after_get(self, ctx: HookContext) -> None:
        if ctx.error is not None:
            return
        item = ctx.result
        if isinstance(item, dict):
            annotate_memory_result(item)

    def after_get_all(self, ctx: HookContext) -> None:
        if ctx.error is not None:
            return
        result = ctx.result
        if isinstance(result, dict) and "results" in result:
            for item in result["results"]:
                if isinstance(item, dict):
                    annotate_memory_result(item)

    def after_search(self, ctx: HookContext) -> None:
        if ctx.error is not None:
            return
        result = ctx.result
        if isinstance(result, dict) and "results" in result:
            for item in result["results"]:
                if isinstance(item, dict):
                    annotate_memory_result(item)

    # ------------------------------------------------------------------
    # async variants
    # ------------------------------------------------------------------
    async def before_add_async(self, ctx: HookContext) -> None:
        import asyncio

        await asyncio.to_thread(self.before_add, ctx)

    async def after_get_async(self, ctx: HookContext) -> None:
        import asyncio

        await asyncio.to_thread(self.after_get, ctx)

    async def after_get_all_async(self, ctx: HookContext) -> None:
        import asyncio

        await asyncio.to_thread(self.after_get_all, ctx)

    async def after_search_async(self, ctx: HookContext) -> None:
        import asyncio

        await asyncio.to_thread(self.after_search, ctx)

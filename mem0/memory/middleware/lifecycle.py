"""
Lifecycle Middleware.

Handles TTL / lifecycle concerns:

* ``before_add`` — resolves the effective ``expires_at`` / ``ttl_source``
  from the request parameters and configured policies, injecting them into
  the metadata dict that will be persisted with each new memory.
* ``after_get`` / ``after_get_all`` / ``after_search`` — annotates the
  returned memory dicts with computed ``ttl_state`` / normalised
  ``expires_at`` / defaulted ``ttl_source``.

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

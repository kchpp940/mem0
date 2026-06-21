"""
History Middleware.

Writes memory change events (ADD / UPDATE / DELETE) to the SQLite history
store via the owning Memory's ``db`` (SQLiteManager) attribute.

The core Memory methods do **not** write history directly.  Instead they
stash the records they want persisted into ``ctx.extras["history_records"]``
(a list of dicts compatible with :meth:`SQLiteManager.batch_add_history`)
and this middleware consumes that list in the corresponding ``after_*``
hook.

For operations that only affect a single memory (``update``, ``delete``)
the record can also be placed at ``ctx.extras["history_record"]`` — the
middleware handles both shapes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from mem0.memory.middleware.base import BaseMiddleware, HookContext

logger = logging.getLogger(__name__)


class HistoryMiddleware(BaseMiddleware):
    name = "history"

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _collect_records(ctx: HookContext) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        extras = ctx.extras

        single = extras.get("history_record")
        if isinstance(single, dict):
            records.append(single)

        batch = extras.get("history_records")
        if isinstance(batch, list):
            for r in batch:
                if isinstance(r, dict):
                    records.append(r)

        return records

    @classmethod
    def _flush(cls, ctx: HookContext) -> None:
        if ctx.error is not None:
            return
        records = cls._collect_records(ctx)
        if not records:
            return
        db = getattr(ctx.memory, "db", None)
        if db is None:
            logger.debug("HistoryMiddleware: no db on memory instance, skipping flush")
            return
        if len(records) == 1:
            r = records[0]
            try:
                db.add_history(
                    r.get("memory_id"),
                    r.get("old_memory"),
                    r.get("new_memory"),
                    r.get("event", "ADD"),
                    created_at=r.get("created_at"),
                    updated_at=r.get("updated_at"),
                    is_deleted=r.get("is_deleted", 0),
                    actor_id=r.get("actor_id"),
                    role=r.get("role"),
                )
            except Exception as exc:
                logger.warning("HistoryMiddleware failed to add history record: %s", exc)
        else:
            try:
                db.batch_add_history(records)
            except Exception as exc:
                logger.warning(
                    "HistoryMiddleware failed to batch-add %d history records: %s",
                    len(records),
                    exc,
                )

    # ------------------------------------------------------------------
    # after hooks (history is written after a successful operation)
    # ------------------------------------------------------------------
    def after_add(self, ctx: HookContext) -> None:
        self._flush(ctx)

    def after_update(self, ctx: HookContext) -> None:
        self._flush(ctx)

    def after_delete(self, ctx: HookContext) -> None:
        self._flush(ctx)

    def after_delete_all(self, ctx: HookContext) -> None:
        self._flush(ctx)

    # ------------------------------------------------------------------
    # async variants
    # ------------------------------------------------------------------
    async def after_add_async(self, ctx: HookContext) -> None:
        import asyncio

        await asyncio.to_thread(self.after_add, ctx)

    async def after_update_async(self, ctx: HookContext) -> None:
        import asyncio

        await asyncio.to_thread(self.after_update, ctx)

    async def after_delete_async(self, ctx: HookContext) -> None:
        import asyncio

        await asyncio.to_thread(self.after_delete, ctx)

    async def after_delete_all_async(self, ctx: HookContext) -> None:
        import asyncio

        await asyncio.to_thread(self.after_delete_all, ctx)

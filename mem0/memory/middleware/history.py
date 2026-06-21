"""
History Middleware.

Writes memory change events (ADD / UPDATE / DELETE) to the SQLite history
store via the owning Memory's ``db`` (SQLiteManager) attribute.

Hook contract
-------------

===========  ===================  ===================================================  ==============================
Phase        Hook                  Effect                                                Reads / Writes
===========  ===================  ===================================================  ==============================
after_add    ``after_add``          Persists ADD history records for all newly            **Reads**: ``ctx.extras["history_records"]``
             (async too)            created memories.                                     (list of dicts), ``ctx.extras["history_record"]``
                                                                                          (single dict), ``ctx.memory.db``, ``ctx.error``
                                                                                          **Writes**: SQLite via ``db.add_history()`` or
                                                                                          ``db.batch_add_history()``

after_update ``after_update``       Persists UPDATE history record.                       **Reads**: ``ctx.extras["history_record"]``,
             (async too)                                                                  ``ctx.memory.db``, ``ctx.error``
                                                                                          **Writes**: SQLite via ``db.add_history()``

after_delete ``after_delete``       Persists DELETE history record.                       **Reads**: ``ctx.extras["history_record"]``,
             (async too)                                                                  ``ctx.memory.db``, ``ctx.error``
                                                                                          **Writes**: SQLite via ``db.add_history()``

after_delete ``after_delete_all``   Persists DELETE history records for bulk deletion.    **Reads**: ``ctx.extras["history_records"]``,
_all         (async too)                                                                  ``ctx.memory.db``, ``ctx.error``
                                                                                          **Writes**: SQLite via ``db.batch_add_history()``
===========  ===================  ===================================================  ==============================

Critical behaviour
------------------
This middleware is marked **critical** (``critical = True``).  If the
SQLite write fails the exception is *not* swallowed — it is recorded on
``ctx.hook_errors`` and, after all after-hooks have run, a
:class:`~mem0.memory.middleware.base.MiddlewareError` is raised so the
caller knows that the history side-effect did not land.

Guard clauses
-------------
* If ``ctx.error is not None`` (the core operation failed), no history
  is written — there is nothing meaningful to record.
* If ``ctx.memory.db`` is ``None``, the flush is skipped with a debug log.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from mem0.memory.middleware.base import BaseMiddleware, HookContext

logger = logging.getLogger(__name__)


class HistoryMiddleware(BaseMiddleware):
    name = "history"
    critical = True

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
        else:
            db.batch_add_history(records)

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

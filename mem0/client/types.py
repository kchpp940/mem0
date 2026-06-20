"""Pydantic option models for MemoryClient methods.

These models provide IDE autocompletion, runtime validation, and type safety.
Methods accept both typed options and **kwargs for backward compatibility.

Identity fields (user_id, agent_id, app_id, run_id) must be passed inside
the ``filters`` dict — the v3 API does not accept them at the top level.

All models are re-exported from the shared schema contract
(``mem0.schema.models``) so that field definitions stay in sync across
server, CLI, and SDK.
"""

from mem0.schema.models import (
    AddMemoryOptions,
    DeleteAllMemoryOptions,
    GetAllMemoryOptions,
    ProjectUpdateOptions,
    SearchMemoryOptions,
    UpdateMemoryOptions,
)

__all__ = [
    "AddMemoryOptions",
    "SearchMemoryOptions",
    "GetAllMemoryOptions",
    "DeleteAllMemoryOptions",
    "UpdateMemoryOptions",
    "ProjectUpdateOptions",
]

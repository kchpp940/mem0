"""Command registry — central descriptor for every CLI command.

Each command declares its *name*, *scope* requirements, *payload builder*,
*backend method*, *renderer*, and behavioural flags in a single
:class:`CommandDescriptor`.  The generic :func:`run_command` orchestrates
the full lifecycle so individual command functions never re-implement the
build-context → build-payload → call-backend → render-result loop.

Commands that need custom logic (e.g. dry-run short-circuits, confirmation
prompts, or multi-step imports) supply an ``action_override`` instead of
the standard builder/method/renderer triple.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from mem0_cli.core.wrapper import CommandContext

# Type aliases for readability
PayloadBuilder = Callable[..., dict[str, Any]]
Renderer = Callable[..., None]
ActionOverride = Callable[[CommandContext, dict[str, Any]], None]
PreValidate = Callable[..., None]


@dataclass(frozen=True)
class CommandDescriptor:
    """Declarative specification for a single CLI command.

    The registry stores one :class:`CommandDescriptor` per command; the
    generic executor reads the descriptor and drives the command lifecycle.

    Fields
    ------
    name:
        Human-readable command name (used in agent-mode envelopes).
    backend_method:
        Name of the :class:`Backend` method to call.  ``None`` for commands
        that don't hit the backend (e.g. ``config show``).
    renderer:
        Callable that receives ``(render_ctx, result, **extra)`` and
        produces the user-visible output.
    needs_scope:
        Whether the command accepts ``--user-id / --agent-id / --app-id / --run-id``.
    payload_builder:
        Callable that transforms raw CLI options into a ``dict`` of kwargs
        for the backend method.  ``None`` when the backend method takes
        positional/keyword args directly.
    spinner:
        Text shown in the stderr spinner while the command runs.
    pre_validate:
        Optional callable invoked **before** context construction (e.g.
        ``require_positive(top_k)``).  Receives the same kwargs as the
        command function.
    action_override:
        When set, the generic executor delegates the full action body to
        this callable instead of the default payload→backend→renderer
        pipeline.  Use for commands with non-trivial control flow (imports,
        dry-run branches, confirmation prompts).
    renderer_extras:
        Static extra kwargs forwarded to the renderer on every invocation.
        Useful for commands whose renderer signature requires fields that
        aren't part of the backend result (e.g. ``memory_id``, ``dry_run``).
    confirm_message:
        If set, a destructive-operation confirmation prompt is shown before
        calling the backend (unless ``--force`` is passed).
    dry_run_short_circuit:
        If ``True``, the generic executor skips the backend call when
        ``dry_run=True`` and synthesises a ``{"dry_run": True}`` result.
    """

    name: str
    backend_method: str | None
    renderer: Renderer | None
    needs_scope: bool = False
    payload_builder: PayloadBuilder | None = None
    spinner: str | None = None
    pre_validate: PreValidate | None = None
    action_override: ActionOverride | None = None
    renderer_extras: dict[str, Any] = field(default_factory=dict)
    confirm_message: str | None = None
    dry_run_short_circuit: bool = False


# ── Registry ───────────────────────────────────────────────────────────────

COMMAND_REGISTRY: dict[str, CommandDescriptor] = {}


def register(desc: CommandDescriptor) -> CommandDescriptor:
    """Register *desc* and return it unchanged (decorator-friendly)."""
    COMMAND_REGISTRY[desc.name] = desc
    return desc


def get_descriptor(name: str) -> CommandDescriptor:
    """Look up a descriptor by name; raise :class:`KeyError` if missing."""
    return COMMAND_REGISTRY[name]


# ── Generic executor ───────────────────────────────────────────────────────


def run_command(
    desc: CommandDescriptor,
    *,
    backend: Any,
    config: Any = None,
    output: str = "text",
    dry_run: bool = False,
    force: bool = False,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    payload_kwargs: dict[str, Any] | None = None,
    renderer_extras: dict[str, Any] | None = None,
) -> None:
    """Execute a command described by *desc* through the unified pipeline.

    Parameters
    ----------
    desc:
        The :class:`CommandDescriptor` that declares the command's behaviour.
    backend:
        The :class:`Backend` instance (or mock) to call.
    config:
        Optional :class:`Mem0Config`.  ``None`` → auto-created.
    output:
        Output mode string (``"text"`` / ``"json"`` / ``"agent"`` / …).
    dry_run:
        When ``True`` and ``desc.dry_run_short_circuit`` is set, skip the
        backend call and synthesise a dry-run result.
    force:
        Passed to the confirmation prompt when ``desc.confirm_message`` is set.
    user_id / agent_id / app_id / run_id:
        Scope filters (only used when ``desc.needs_scope``).
    payload_kwargs:
        Extra keyword arguments forwarded to the ``payload_builder``.
    renderer_extras:
        Additional keyword arguments forwarded to the renderer (merged on
        top of ``desc.renderer_extras``).
    """
    from mem0_cli.core.wrapper import build_command_context, confirm_destructive, execute

    scope_kwargs: dict[str, str | None] = {}
    if desc.needs_scope:
        scope_kwargs = {
            "user_id": user_id,
            "agent_id": agent_id,
            "app_id": app_id,
            "run_id": run_id,
        }

    ctx = build_command_context(
        command_name=desc.name,
        backend=backend,
        config=config,
        output=output,
        **scope_kwargs,
    )

    def action(_ctx: CommandContext) -> None:
        # --- action_override: full custom logic ---
        if desc.action_override is not None:
            merged_kwargs = {**(payload_kwargs or {})}
            if desc.needs_scope:
                merged_kwargs["scope"] = _ctx.ids
            desc.action_override(_ctx, merged_kwargs)
            return

        # --- confirm prompt ---
        if desc.confirm_message:
            confirm_destructive(_ctx, desc.confirm_message, force=force)

        # --- dry-run short-circuit ---
        if dry_run and desc.dry_run_short_circuit:
            result: Any = {"dry_run": True, "would_delete": True}
            if desc.renderer is not None:
                extras = {**desc.renderer_extras, **(renderer_extras or {}), "dry_run": True}
                desc.renderer(_ctx.render_ctx, result, **extras)
            return

        # --- standard pipeline: payload → backend → renderer ---
        payload: dict[str, Any] = {}
        if desc.payload_builder is not None:
            builder_kwargs = {**(payload_kwargs or {})}
            if desc.needs_scope:
                builder_kwargs["scope"] = _ctx.ids
            payload = desc.payload_builder(**builder_kwargs)
        elif payload_kwargs:
            payload = payload_kwargs

        method = getattr(_ctx.backend, desc.backend_method)
        if payload:
            result = method(**payload)
        else:
            result = method()

        if desc.renderer is not None:
            extras = {**desc.renderer_extras, **(renderer_extras or {})}
            desc.renderer(_ctx.render_ctx, result, **extras)

    execute(ctx, action, spinner=desc.spinner)

"""Unified command execution wrapper.

The :class:`CommandContext` and :func:`execute` helper orchestrate the
full lifecycle of a CLI command:

1. Build :class:`CommandContext` (backend + config + scope + render ctx).
2. Run the user's command logic inside ``execute()``.
3. Intercept any exception and pass it through ``errors.map_exception``.
4. Print a consistent error (using agent-mode JSON envelope when needed).
5. Exit with the correct :data:`CLIError.exit_code`.

All Typer command functions should go through :func:`execute` so they stay
small (parameter collection only) and never re-implement error rendering,
scope resolution or output-mode handling.
"""

from __future__ import annotations

import time as _time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, TypeVar

import typer

from mem0_cli.branding import print_error as _branding_print_error

from .console import err_console, stdout_console
from .errors import AuthError, CLIError, ConfigError, InputError, map_exception
from .options import ScopeIDs, resolve_scope
from .renderers import RenderContext, resolve_output_mode

_T = TypeVar("_T")


# ── Command context ───────────────────────────────────────────────────────


@dataclass
class CommandContext:
    """Everything a command handler needs to do its job.

    Constructed by :func:`build_command_context`; passed through
    :func:`execute` to the command's action function.
    """

    backend: Any
    config: Any
    scope: ScopeIDs
    render_ctx: RenderContext

    @property
    def ids(self) -> dict[str, str | None]:
        """Shortcut for passing scope directly into backend methods."""

        return self.scope.as_dict()


def build_command_context(
    *,
    command_name: str,
    backend: Any,
    config: Any = None,
    output: str,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
    extra_scope: dict[str, str | None] | None = None,
) -> CommandContext:
    """Build :class:`CommandContext` with sensible defaults.

    Calls :func:`resolve_scope` so the scope IDs honour the explicit-flags
    vs config-defaults precedence.

    If *config* is ``None`` a fresh :class:`Mem0Config` is used — this keeps
    older callers / tests that don't pass a config working.
    """

    from mem0_cli.state import set_current_command

    if config is None:
        from mem0_cli.config import Mem0Config

        config = Mem0Config()

    set_current_command(command_name)

    scope = resolve_scope(
        config,
        user_id=user_id,
        agent_id=agent_id,
        app_id=app_id,
        run_id=run_id,
    )
    if extra_scope:
        # Allow commands to layer on additional scope fields (rare).
        merged = {**scope.as_dict(), **{k: v for k, v in extra_scope.items() if v}}
        scope = ScopeIDs(**merged)

    render_ctx = RenderContext(
        command_name=command_name,
        output_mode=resolve_output_mode(output),
        scope=scope.as_dict(),
        started_at=_time.perf_counter(),
    )

    return CommandContext(
        backend=backend,
        config=config,
        scope=scope,
        render_ctx=render_ctx,
    )


# ── Timed backend spinner ─────────────────────────────────────────────────


@contextmanager
def timed(ctx: CommandContext, message: str) -> Generator[None, None, None]:
    """Thin wrapper around :func:`branding.timed_status` using the
    standard stderr console.
    """

    from mem0_cli.branding import timed_status

    with timed_status(err_console, message):
        yield


# ── Confirmation helpers ──────────────────────────────────────────────────


def confirm_destructive(ctx: CommandContext, message: str, *, force: bool) -> None:
    """Ask for confirmation unless ``--force`` or running in agent mode.

    In agent mode destructive ops *require* ``--force`` and raise
    :class:`InputError` otherwise.
    """

    from mem0_cli.state import is_agent_mode

    if is_agent_mode():
        if not force:
            raise InputError("Destructive operation requires --force in agent mode.")
        return
    if force:
        return
    if not typer.confirm(f"\n  ⚠  {message} This cannot be undone."):
        from mem0_cli.branding import print_info

        print_info(stdout_console, "Cancelled.")
        raise typer.Exit(0)


# ── Unified execute() wrapper ─────────────────────────────────────────────


def execute(
    ctx: CommandContext,
    action: Callable[[CommandContext], _T],
    *,
    spinner: str | None = None,
) -> _T:
    """Run *action* with unified exception handling.

    *spinner* — optional status message shown while ``action`` runs
    (sent to stderr, never interferes with JSON output).
    """

    try:
        if spinner:
            from mem0_cli.branding import timed_status

            with timed_status(err_console, spinner):
                return action(ctx)
        return action(ctx)
    except CLIError as exc:
        _render_cli_error(exc)
        raise typer.Exit(exc.exit_code) from None
    except typer.Exit:
        raise
    except SystemExit:
        raise
    except Exception as exc:
        info = map_exception(exc)
        _render_cli_error(info.kind(info.message, hint=info.hint))
        raise typer.Exit(info.kind.exit_code) from None


def _render_cli_error(exc: CLIError) -> None:
    """Render a :class:`CLIError` honouring agent-mode JSON envelopes."""

    from mem0_cli.state import get_current_command, is_agent_mode, take_notice

    if is_agent_mode():
        import json as _json
        import sys as _sys

        envelope = {
            "status": "error",
            "command": get_current_command(),
            "error": exc.message,
            "error_kind": exc.__class__.__name__,
            "data": None,
        }
        if exc.hint:
            envelope["hint"] = exc.hint
        notice = take_notice()
        if notice:
            envelope["mem0_notice"] = notice
        print(_json.dumps(envelope, default=str), file=_sys.stdout)
        return

    target = err_console
    if isinstance(exc, (InputError, AuthError, ConfigError)):
        target = err_console
    _branding_print_error(target, exc.message, hint=exc.hint)


def _render_cli_error_shim(exc: CLIError) -> None:
    """Public shim used by :mod:`app.py` for errors raised outside ``execute()``.

    Behaviour is identical to :func:`_render_cli_error`.
    """

    _render_cli_error(exc)


# ── Backend + config loader (thin replacement for app._get_backend_and_config) ──


def load_backend_and_config(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
):
    """Load backend and config, raising :class:`CLIError` subclasses on failure.

    Thin wrapper around the existing helpers in ``app.py``, but raises
    typed errors so the execute wrapper can handle them uniformly.
    """

    import contextlib

    from mem0_cli.backend import get_backend
    from mem0_cli.config import load_config, save_config

    config = load_config()

    if api_key:
        config.platform.api_key = api_key
    if base_url:
        config.platform.base_url = base_url

    if not config.platform.api_key:
        raise ConfigError(
            "No API key configured.",
            hint="Run 'mem0 init' or set MEM0_API_KEY environment variable.",
        )

    backend = get_backend(config)

    try:
        ping_data = backend.ping(timeout=5.0)
        email = ping_data.get("user_email") if isinstance(ping_data, dict) else None
        if email and config.platform.user_email != email:
            config.platform.user_email = email
            with contextlib.suppress(Exception):
                save_config(config)
    except AuthError:
        raise
    except Exception:
        from mem0_cli.branding import print_warning

        print_warning(err_console, "Could not validate API key (network issue). Proceeding anyway.")

    return backend, config

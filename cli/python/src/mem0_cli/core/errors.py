"""CLI error hierarchy + mapper.

All exceptions raised *during command execution* should map to one of the
classes below so the execution wrapper can render them consistently.

The ``map_exception`` helper converts arbitrary HTTP / backend / IO errors
into the appropriate typed CLIError subclass with a helpful message.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass


class CLIError(Exception):
    """Base class for user-facing CLI errors.

    Attributes:
        message:   The short, user-facing error message.
        hint:      Optional one-line hint (e.g. run ``mem0 init``).
        exit_code: Exit code the wrapper will produce.
    """

    exit_code: int = 1

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class InputError(CLIError):
    """Raised when user input (options, stdin, files) is invalid."""

    exit_code = 2


class ConfigError(CLIError):
    """Raised when the config file / environment is in a bad state."""

    exit_code = 3


class AuthError(CLIError):
    """Raised on authentication failure (missing / invalid API key)."""

    exit_code = 4


class BackendError(CLIError):
    """Raised when the backend returns an error we can't otherwise classify."""

    exit_code = 5


class NotFoundError(CLIError):
    """Raised when the requested resource (memory, event, entity...) doesn't exist."""

    exit_code = 6


@dataclass
class ErrorInfo:
    kind: type[CLIError]
    message: str
    hint: str | None = None


def _try_extract_message(exc: Exception) -> str:
    """Best-effort extraction of a readable message from an exception."""
    try:
        import json as _json

        text = str(exc)
        # httpx.HTTPStatusError / requests.HTTPError bodies
        if hasattr(exc, "response"):
            resp = exc.response  # type: ignore[attr-defined]
            try:
                body = resp.text if hasattr(resp, "text") else resp.read().decode()
            except Exception:
                body = ""
            if body:
                try:
                    data = _json.loads(body)
                    for key in ("detail", "message", "error", "msg"):
                        if key in data:
                            val = data[key]
                            if isinstance(val, str):
                                return val
                            if isinstance(val, list):  # fastapi style [[msg, ...]]
                                return " ".join(str(v) for v in val)
                except Exception:
                    pass
                if body and len(body) < 300:
                    return f"{text}: {body}"
    except Exception:
        pass
    return str(exc) or exc.__class__.__name__


def map_exception(exc: Exception) -> ErrorInfo:
    """Map a raw exception to a typed :class:`ErrorInfo`.

    Order matters: specific checks before generic ones.
    """

    # ---- 1. Already our own errors ----
    if isinstance(exc, CLIError):
        return ErrorInfo(kind=type(exc), message=exc.message, hint=exc.hint)

    # ---- 2. Import / lookup backend platform.AuthError without circular import ----
    try:
        from mem0_cli.backend.platform import AuthError as PlatformAuthError

        if isinstance(exc, PlatformAuthError):
            return ErrorInfo(
                kind=AuthError,
                message="Invalid or expired API key.",
                hint="Run 'mem0 init' or set MEM0_API_KEY environment variable.",
            )
    except Exception:
        pass

    # ---- 3. Common Python built-ins ----
    if isinstance(exc, FileNotFoundError):
        return ErrorInfo(kind=InputError, message=f"File not found: {exc.filename}" if exc.filename else str(exc))
    if isinstance(exc, IsADirectoryError):
        return ErrorInfo(kind=InputError, message="Expected a file but got a directory.")
    if isinstance(exc, PermissionError):
        return ErrorInfo(kind=InputError, message="Permission denied.", hint="Check file permissions.")
    if isinstance(exc, (ValueError, TypeError)):
        return ErrorInfo(kind=InputError, message=str(exc) or "Invalid input.")
    if isinstance(exc, KeyError):
        return ErrorInfo(kind=InputError, message=f"Missing key: {exc}")
    if isinstance(exc, TimeoutError):
        return ErrorInfo(
            kind=BackendError,
            message="Request timed out.",
            hint="Check your network connection or retry later.",
        )
    if isinstance(exc, ConnectionError):
        return ErrorInfo(
            kind=BackendError,
            message="Could not connect to the Mem0 API.",
            hint="Check your base URL and network connection.",
        )

    # ---- 4. HTTP library specific (httpx, requests) ----
    _status: int | None = None
    if hasattr(exc, "response") and hasattr(exc.response, "status_code"):
        with contextlib.suppress(Exception):
            _status = int(exc.response.status_code)  # type: ignore[attr-defined]

    msg = _try_extract_message(exc)

    if _status == 401 or _status == 403:
        return ErrorInfo(
            kind=AuthError,
            message="Authentication failed.",
            hint="Run 'mem0 init' or set MEM0_API_KEY environment variable.",
        )
    if _status == 404:
        return ErrorInfo(kind=NotFoundError, message=msg or "Resource not found.")
    if _status == 422:
        return ErrorInfo(kind=InputError, message=msg or "Invalid request parameters.")
    if _status is not None and _status >= 500:
        return ErrorInfo(
            kind=BackendError,
            message=f"Server error ({_status}).",
            hint="Try again later or contact support.",
        )

    # ---- 5. Fallback ----
    return ErrorInfo(kind=BackendError, message=msg)

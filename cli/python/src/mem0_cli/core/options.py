"""Option parsing, validation, and stdin/file loading helpers.

These functions take *raw CLI option values* (strings / paths / None) and
return the strongly-typed Python objects the backend or renderer expects,
raising :class:`mem0_cli.core.errors.InputError` on malformed input.
"""

from __future__ import annotations

import json
import os
import re
import stat as _stat_mod
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from mem0_cli.core.errors import InputError

# ── Scope resolution ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScopeIDs:
    """Resolved entity IDs for a command."""

    user_id: str | None = None
    agent_id: str | None = None
    app_id: str | None = None
    run_id: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "app_id": self.app_id,
            "run_id": self.run_id,
        }

    def non_null(self) -> dict[str, str]:
        return {k: v for k, v in self.as_dict().items() if v}

    def scope_label(self) -> str:
        """Human-readable scope description for confirmation prompts."""
        parts = [f"{k.replace('_', '')[:4]}={v}" for k, v in self.non_null().items()]
        return ", ".join(parts) if parts else "ALL entities"


def resolve_scope(
    config,
    *,
    user_id: str | None = None,
    agent_id: str | None = None,
    app_id: str | None = None,
    run_id: str | None = None,
) -> ScopeIDs:
    """Resolve entity IDs: CLI flag > config default > None.

    If any explicit ID is provided only explicit IDs are used (to avoid
    over-filtering). If no explicit IDs are provided all configured
    defaults are applied.
    """

    explicit = [user_id, agent_id, app_id, run_id]
    if any(explicit):
        return ScopeIDs(
            user_id=user_id or None,
            agent_id=agent_id or None,
            app_id=app_id or None,
            run_id=run_id or None,
        )
    return ScopeIDs(
        user_id=getattr(getattr(config, "defaults", None), "user_id", None) or None,
        agent_id=getattr(getattr(config, "defaults", None), "agent_id", None) or None,
        app_id=getattr(getattr(config, "defaults", None), "app_id", None) or None,
        run_id=getattr(getattr(config, "defaults", None), "run_id", None) or None,
    )


# ── JSON parsing helpers ──────────────────────────────────────────────────


def parse_json(raw: str, *, field: str) -> Any:
    """Parse a JSON string, raising InputError on failure.

    *field* describes the option name for the error message.
    """

    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputError(f"Invalid JSON in {field}: {exc}") from None


def parse_json_option(raw: str | None, *, field: str) -> Any:
    if not raw:
        return None
    return parse_json(raw, field=field)


def parse_metadata(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputError(f"Invalid JSON in --metadata: {exc}") from None
    if not isinstance(parsed, dict):
        raise InputError("--metadata must be a JSON object.")
    return parsed


def parse_categories(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
        if isinstance(parsed, str):
            return [c.strip() for c in parsed.split(",") if c.strip()]
    except json.JSONDecodeError:
        pass
    return [c.strip() for c in raw.split(",") if c.strip()]


def parse_filter_json(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputError(f"Invalid JSON in --filter: {exc}") from None
    if not isinstance(parsed, dict):
        raise InputError("--filter must be a JSON object.")
    return parsed


def parse_fields(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [f.strip() for f in raw.split(",") if f.strip()]


# ── File & stdin reading ──────────────────────────────────────────────────


def stdin_is_piped() -> bool:
    """Return True only when stdin is an actual pipe or file redirect."""

    from mem0_cli.state import is_agent_mode

    if is_agent_mode():
        return False
    try:
        mode = os.fstat(sys.stdin.fileno()).st_mode
        return _stat_mod.S_ISFIFO(mode) or _stat_mod.S_ISREG(mode)
    except Exception:
        return False


def read_stdin() -> str | None:
    """Read stdin if it's a pipe/redirect; else None."""

    if stdin_is_piped():
        data = sys.stdin.read().strip()
        return data or None
    return None


def read_file_text(path: Path | str) -> str:
    try:
        return Path(path).read_text()
    except FileNotFoundError:
        raise InputError(f"File not found: {path}") from None
    except IsADirectoryError:
        raise InputError(f"Expected a file, got a directory: {path}") from None
    except PermissionError:
        raise InputError(f"Permission denied: {path}") from None
    except Exception as exc:
        raise InputError(f"Failed to read file '{path}': {exc}") from None


def read_file_json(path: Path | str, *, field: str = "file") -> Any:
    raw = read_file_text(path)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputError(f"Failed to parse JSON file '{path}': {exc}") from None


def read_messages_from_file(path: Path | str | None) -> list[dict] | None:
    if not path:
        return None
    data = read_file_json(path, field="--file")
    if isinstance(data, list):
        return [d if isinstance(d, dict) else {} for d in data]
    if isinstance(data, dict):
        if isinstance(data.get("messages"), list):
            return [d if isinstance(d, dict) else {} for d in data["messages"]]
        return [data]
    raise InputError("--file JSON must be a list or object.")


# ── Date parsing ──────────────────────────────────────────────────────────


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_expires(raw: str | None) -> str | None:
    if not raw:
        return None
    if not _DATE_RE.match(raw):
        raise InputError(
            "Invalid date format for --expires. Use YYYY-MM-DD (e.g. 2025-12-31)."
        )
    try:
        if date.fromisoformat(raw) <= date.today():
            raise InputError("--expires date must be in the future.")
    except ValueError as exc:
        raise InputError(f"Invalid date: {exc}") from None
    return raw


# ── Generic validators ────────────────────────────────────────────────────


def require_one(*values: Any, message: str) -> None:
    """Ensure at least one value is truthy; else raise InputError."""

    if not any(v is not None and v != "" for v in values):
        raise InputError(message)


def require_positive(value: int, *, field: str, minimum: int = 1) -> None:
    if value < minimum:
        raise InputError(f"{field} must be >= {minimum}.")


def require_between(value: float, *, field: str, minimum: float, maximum: float) -> None:
    if not (minimum <= value <= maximum):
        raise InputError(f"{field} must be between {minimum} and {maximum}.")

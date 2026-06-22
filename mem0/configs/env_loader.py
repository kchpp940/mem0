import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

from dotenv import load_dotenv


@dataclass
class ConfigError:
    key: str
    message: str
    suggestion: str


class ConfigValidationError(Exception):
    def __init__(self, errors: List[ConfigError]):
        self.errors = errors
        lines = ["\n" + "=" * 72]
        lines.append("  CONFIGURATION ERROR — the following environment variables are missing or invalid:")
        lines.append("=" * 72)
        for err in errors:
            lines.append(f"\n  ❌ {err.key}")
            lines.append(f"     {err.message}")
            lines.append(f"     💡 {err.suggestion}")
        lines.append("\n" + "=" * 72)
        lines.append("  See the .env.example file in the repository root for all available variables.")
        lines.append("=" * 72 + "\n")
        super().__init__("\n".join(lines))


def load_env(search_paths: Optional[List[str]] = None) -> None:
    """Load .env file from common locations.

    Searches (in order):
      1. Explicit paths passed in
      2. Current working directory
      3. Parent directories (up to repo root)
    """
    if search_paths is None:
        search_paths = []

    cwd = os.getcwd()
    candidates = list(search_paths)
    candidates.append(os.path.join(cwd, ".env"))

    parent = os.path.dirname(cwd)
    for _ in range(4):
        if parent and parent != "/":
            candidates.append(os.path.join(parent, ".env"))
            parent = os.path.dirname(parent)

    for path in candidates:
        if path and os.path.isfile(path):
            load_dotenv(path, override=False)
            return


def get_env(key: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    """Read an environment variable with optional fallback to a default."""
    value = os.environ.get(key, default)
    if required and (value is None or value == ""):
        raise ConfigValidationError(
            [
                ConfigError(
                    key=key,
                    message=f"Environment variable {key} is required but not set.",
                    suggestion=f"Set {key}=<value> in your .env file or shell environment.",
                )
            ]
        )
    return value


def get_env_int(key: str, default: Optional[int] = None, required: bool = False) -> Optional[int]:
    raw = get_env(key, default=str(default) if default is not None else None, required=required)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigValidationError(
            [
                ConfigError(
                    key=key,
                    message=f"Expected an integer but got '{raw}'.",
                    suggestion=f"Set {key} to a valid integer (e.g. {key}=5432).",
                )
            ]
        )


def get_env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def validate_required(required: Dict[str, str]) -> None:
    """Validate that all required env vars are set.

    Args:
        required: mapping of env var name -> human-readable description
    """
    errors: List[ConfigError] = []
    for key, description in required.items():
        value = os.environ.get(key)
        if not value:
            suggestion_map = {
                "POSTGRES_PASSWORD": "Set POSTGRES_PASSWORD in your .env file. For local development you can use any non-empty value.",
                "JWT_SECRET": "Generate a secure key with: openssl rand -base64 48",
                "OPENAI_API_KEY": "Get an API key from https://platform.openai.com/api-keys and set OPENAI_API_KEY=<key>",
                "DATABASE_URL": "Set DATABASE_URL=postgresql+psycopg://user:pass@host:port/dbname or use SQLite: sqlite:///./openmemory.db",
            }
            errors.append(
                ConfigError(
                    key=key,
                    message=f"{description} is required but not set or is empty.",
                    suggestion=suggestion_map.get(
                        key, f"Set {key}=<value> in your .env file or shell environment."
                    ),
                )
            )
    if errors:
        raise ConfigValidationError(errors)


def validate_postgres_connection() -> List[ConfigError]:
    """Return a list of Postgres-related configuration problems (if any)."""
    errors: List[ConfigError] = []
    password = os.environ.get("POSTGRES_PASSWORD")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")

    if not password:
        errors.append(
            ConfigError(
                key="POSTGRES_PASSWORD",
                message="POSTGRES_PASSWORD is not set. Postgres will refuse connections.",
                suggestion="Set POSTGRES_PASSWORD in your .env file. In docker-compose this is also required for the postgres service to start.",
            )
        )

    try:
        int(port)
    except ValueError:
        errors.append(
            ConfigError(
                key="POSTGRES_PORT",
                message=f"POSTGRES_PORT='{port}' is not a valid port number.",
                suggestion="Set POSTGRES_PORT to a valid integer port (default: 5432).",
            )
        )

    return errors


def build_postgres_url(
    user: Optional[str] = None,
    password: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
    dbname: Optional[str] = None,
    require_password: bool = True,
) -> str:
    """Build a Postgres connection URL from env vars with explicit fallbacks."""
    user = user or os.environ.get("POSTGRES_USER", "postgres")
    password = password or os.environ.get("POSTGRES_PASSWORD", "")
    host = host or os.environ.get("POSTGRES_HOST", "localhost")
    port = port or get_env_int("POSTGRES_PORT", 5432)
    dbname = dbname or os.environ.get("POSTGRES_DB", "postgres")

    if require_password and not password:
        raise ConfigValidationError(
            [
                ConfigError(
                    key="POSTGRES_PASSWORD",
                    message="Cannot build Postgres URL: POSTGRES_PASSWORD is empty.",
                    suggestion="Set POSTGRES_PASSWORD in your .env file or pass password= explicitly.",
                )
            ]
        )

    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{dbname}"


def fatal_config_error(errors: List[ConfigError]) -> None:
    """Print a friendly config error and exit with code 2."""
    try:
        raise ConfigValidationError(errors)
    except ConfigValidationError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)

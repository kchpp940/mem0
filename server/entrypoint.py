#!/usr/bin/env python3
"""
Docker container entrypoint for Mem0 services.

Performs pre-flight configuration checks, runs database migrations if requested,
then execs the main process.

Usage:
    docker_entrypoint.py [--service server|openmemory-api] [--run-migrations] [--] <command>...

Exit codes:
    0: success (execs into the command)
    2: configuration error (invalid/missing env vars)
    3: migration failure
"""

import argparse
import os
import subprocess
import sys
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent


def load_env_loader():
    """Load the _env_loader module from the service directory or repo root."""
    candidates = [
        Path.cwd() / "_env_loader.py",
        REPO_ROOT / "server" / "_env_loader.py",
        REPO_ROOT / "openmemory" / "api" / "_env_loader.py",
        REPO_ROOT / "mem0" / "configs" / "env_loader.py",
    ]
    for path in candidates:
        if path.is_file():
            spec = spec_from_file_location("_env_loader", path)
            if spec and spec.loader:
                module = module_from_spec(spec)
                sys.modules["_env_loader"] = module
                spec.loader.exec_module(module)
                return module
    print(
        "\n" + "=" * 72
        + "\n  ERROR: Could not find _env_loader.py in the container.\n"
        + "  Make sure _env_loader.py is copied into the service directory in the Dockerfile.\n"
        + "=" * 72
        + "\n",
        file=sys.stderr,
    )
    sys.exit(2)


def validate_server_config(env_loader):
    """Run server-specific configuration validation."""
    errors = []
    errors.extend(env_loader.validate_postgres_connection())

    llm_provider = env_loader.get_env("MEM0_LLM_PROVIDER", "openai")
    embedder_provider = env_loader.get_env("MEM0_EMBEDDER_PROVIDER", "openai")
    openai_key = env_loader.get_env("OPENAI_API_KEY", "")

    if llm_provider == "openai" and not openai_key:
        errors.append(
            env_loader.ConfigError(
                key="OPENAI_API_KEY",
                message="LLM provider is 'openai' but OPENAI_API_KEY is not set.",
                suggestion="Set OPENAI_API_KEY=<your-key> in your .env, or choose a different MEM0_LLM_PROVIDER.",
            )
        )
    if embedder_provider == "openai" and not openai_key:
        errors.append(
            env_loader.ConfigError(
                key="OPENAI_API_KEY",
                message="Embedder provider is 'openai' but OPENAI_API_KEY is not set.",
                suggestion="Set OPENAI_API_KEY=<your-key> in your .env, or choose a different MEM0_EMBEDDER_PROVIDER.",
            )
        )

    auth_disabled = env_loader.get_env_bool("AUTH_DISABLED", False)
    jwt_secret = env_loader.get_env("JWT_SECRET", "")
    if not auth_disabled and not jwt_secret:
        errors.append(
            env_loader.ConfigError(
                key="JWT_SECRET",
                message="JWT_SECRET is required when AUTH_DISABLED is not set to true.",
                suggestion="Either set JWT_SECRET (generate with: openssl rand -base64 48) or set AUTH_DISABLED=true for local development only.",
            )
        )

    return errors


def validate_openmemory_api_config(env_loader):
    """Run openmemory-api-specific configuration validation."""
    errors = []

    database_url = env_loader.get_env("DATABASE_URL", "")
    if not database_url:
        pg_errors = env_loader.validate_postgres_connection()
        if pg_errors:
            errors.extend(pg_errors)
            errors.append(
                env_loader.ConfigError(
                    key="DATABASE_URL",
                    message="No DATABASE_URL set and POSTGRES_* configuration is incomplete.",
                    suggestion="Either set DATABASE_URL directly or configure all POSTGRES_* variables.",
                )
            )

    vector_store_provider = env_loader.get_env(
        "VECTOR_STORE_PROVIDER", env_loader.get_env("VECTOR_STORE", "qdrant")
    )
    llm_provider = env_loader.get_env(
        "MEM0_LLM_PROVIDER", env_loader.get_env("LLM_PROVIDER", "openai")
    )

    if llm_provider == "openai" and not env_loader.get_env("OPENAI_API_KEY", ""):
        errors.append(
            env_loader.ConfigError(
                key="OPENAI_API_KEY",
                message=f"LLM provider is '{llm_provider}' but OPENAI_API_KEY is not set.",
                suggestion="Get an API key from https://platform.openai.com/api-keys and set OPENAI_API_KEY=<key> in your .env, or choose a different MEM0_LLM_PROVIDER.",
            )
        )

    if vector_store_provider == "qdrant":
        qdrant_host = env_loader.get_env(
            "QDRANT_HOST", env_loader.get_env("MEM0_QDRANT_HOST", "localhost")
        )
        if not qdrant_host:
            errors.append(
                env_loader.ConfigError(
                    key="QDRANT_HOST",
                    message="VECTOR_STORE_PROVIDER is 'qdrant' but QDRANT_HOST is not set.",
                    suggestion="Set QDRANT_HOST to the Qdrant server hostname (e.g. 'localhost' or 'mem0_store' in docker-compose).",
                )
            )

    return errors


def run_migrations():
    """Run Alembic database migrations, if alembic.ini exists in the current directory."""
    if not Path("alembic.ini").is_file():
        return

    print("\n" + "=" * 72)
    print("  Running Alembic database migrations...")
    print("=" * 72)

    try:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=True,
            env=os.environ,
        )
    except subprocess.CalledProcessError as exc:
        print(
            "\n" + "=" * 72
            + "\n  !!! Alembic migration failed — check POSTGRES_* variables and database\n"
            + f"  !!! Exit code: {exc.returncode}\n"
            + "=" * 72
            + "\n",
            file=sys.stderr,
        )
        sys.exit(3)
    except FileNotFoundError:
        print(
            "\n" + "=" * 72
            + "\n  !!! Alembic not found — ensure it is installed in the container.\n"
            + "=" * 72
            + "\n",
            file=sys.stderr,
        )
        sys.exit(3)

    print("  Migrations completed successfully.\n")


def main():
    parser = argparse.ArgumentParser(description="Mem0 service entrypoint")
    parser.add_argument(
        "--service",
        choices=["server", "openmemory-api"],
        required=True,
        help="Which service is being started",
    )
    parser.add_argument(
        "--run-migrations",
        action="store_true",
        help="Run Alembic migrations before starting the service",
    )
    parser.add_argument(
        "command",
        nargs="+",
        help="The command to exec into after pre-flight checks",
    )
    args = parser.parse_args()

    env_loader = load_env_loader()
    env_loader.load_env()

    if args.service == "server":
        errors = validate_server_config(env_loader)
    else:
        errors = validate_openmemory_api_config(env_loader)

    if errors:
        env_loader.fatal_config_error(errors)

    env_vars_loaded = [
        f"  {key}={env_loader.get_env(key, '[not set]')}"
        for key in [
            "MEM0_LLM_PROVIDER",
            "MEM0_EMBEDDER_PROVIDER",
            "VECTOR_STORE_PROVIDER",
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "MEM0_APP_DB_NAME",
            "MEM0_USER_ID",
        ]
    ]

    print("\n" + "=" * 72)
    print(f"  {args.service} configuration loaded:")
    print("\n".join(env_vars_loaded))
    print("=" * 72 + "\n")

    if args.run_migrations:
        run_migrations()

    print("  Starting: " + " ".join(args.command) + "\n")
    os.execvp(args.command[0], args.command)


if __name__ == "__main__":
    main()

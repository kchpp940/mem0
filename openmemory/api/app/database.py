import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _env_loader import (
    ConfigError,
    ConfigValidationError,
    build_postgres_url,
    fatal_config_error,
    get_env,
    load_env,
    validate_postgres_connection,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_env()


def _build_database_url() -> str:
    """Build DATABASE_URL from individual POSTGRES_* vars, or fall back to DATABASE_URL or SQLite."""
    explicit_url = get_env("DATABASE_URL", "")
    if explicit_url:
        return explicit_url

    pg_errors = validate_postgres_connection()
    if not pg_errors:
        try:
            return build_postgres_url()
        except ConfigValidationError:
            pass

    logging.warning(
        "No DATABASE_URL or valid POSTGRES_* configuration found. "
        "Falling back to SQLite: sqlite:///./openmemory.db"
    )
    return "sqlite:///./openmemory.db"


try:
    DATABASE_URL = _build_database_url()
except Exception as exc:
    print(
        f"\n{'=' * 72}\n"
        f"  Failed to determine database URL: {exc}\n"
        f"  Set DATABASE_URL or configure POSTGRES_HOST/PORT/USER/PASSWORD/DB in your .env.\n"
        f"{'=' * 72}\n",
        file=sys.stderr,
    )
    sys.exit(2)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

try:
    engine = create_engine(DATABASE_URL, connect_args=connect_args)
except Exception as exc:
    print(
        f"\n{'=' * 72}\n"
        f"  Failed to connect to database at: {DATABASE_URL.replace('://', '://***:***@') if '@' in DATABASE_URL else DATABASE_URL}\n"
        f"  Underlying error: {exc}\n"
        f"  Verify DATABASE_URL (or POSTGRES_* variables) and that the database server is reachable.\n"
        f"{'=' * 72}\n",
        file=sys.stderr,
    )
    sys.exit(2)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

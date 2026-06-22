import logging
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from _env_loader import (
    ConfigValidationError,
    build_postgres_url,
    fatal_config_error,
    get_env,
    load_env,
    validate_postgres_connection,
)

load_env()


def _build_database_url() -> str:
    errors = validate_postgres_connection()
    if errors:
        fatal_config_error(errors)

    db = get_env("MEM0_APP_DB_NAME", "mem0_app") or get_env("APP_DB_NAME", "mem0_app")
    try:
        return build_postgres_url(dbname=db)
    except ConfigValidationError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)


try:
    engine = create_engine(_build_database_url(), pool_pre_ping=True)
except ConfigValidationError as exc:
    print(str(exc), file=sys.stderr)
    sys.exit(2)
except Exception as exc:
    logging.error(
        "\n%s\n"
        "  Failed to connect to the PostgreSQL database.\n"
        "  Check that POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, and MEM0_APP_DB_NAME are correct.\n"
        "  Underlying error: %s\n"
        "%s",
        "=" * 72,
        exc,
        "=" * 72,
    )
    sys.exit(2)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a SQLAlchemy session."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()

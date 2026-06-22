import datetime
import logging
import sys
from uuid import uuid4

from app.config import DEFAULT_APP_ID, USER_ID
from app.database import Base, SessionLocal, engine
from app.mcp_server import setup_mcp_server
from app.models import App, User
from app.routers import apps_router, backup_router, config_router, memories_router, stats_router
from app.utils.memory import validate_startup_config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_pagination import add_pagination

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

app = FastAPI(title="OpenMemory API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _startup_safety_checks() -> None:
    """Run pre-flight checks before the server accepts requests."""
    try:
        validate_startup_config()
    except SystemExit:
        raise
    except Exception as exc:
        logging.error(
            "\n%s\n"
            "  Startup configuration check failed: %s\n"
            "  Review the environment variables listed in the repository root .env.example.\n"
            "%s",
            "=" * 72,
            exc,
            "=" * 72,
        )
        sys.exit(2)


_startup_safety_checks()

# Create all tables
try:
    Base.metadata.create_all(bind=engine)
except Exception as exc:
    logging.error(
        "\n%s\n"
        "  Failed to create database tables. Check that the database server is running\n"
        "  and that DATABASE_URL or POSTGRES_* variables point to a reachable database.\n"
        "  Underlying error: %s\n"
        "%s",
        "=" * 72,
        exc,
        "=" * 72,
    )
    sys.exit(2)


# Check for USER_ID and create default user if needed
def create_default_user():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.user_id == USER_ID).first()
        if not user:
            user = User(
                id=uuid4(),
                user_id=USER_ID,
                name="Default User",
                created_at=datetime.datetime.now(datetime.UTC),
            )
            db.add(user)
            db.commit()
            logging.info("Created default user: %s", USER_ID)
    except Exception as exc:
        logging.warning("Could not create default user: %s", exc)
    finally:
        db.close()


def create_default_app():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.user_id == USER_ID).first()
        if not user:
            return

        existing_app = (
            db.query(App)
            .filter(App.name == DEFAULT_APP_ID, App.owner_id == user.id)
            .first()
        )

        if existing_app:
            return

        app_record = App(
            id=uuid4(),
            name=DEFAULT_APP_ID,
            owner_id=user.id,
            created_at=datetime.datetime.now(datetime.UTC),
            updated_at=datetime.datetime.now(datetime.UTC),
        )
        db.add(app_record)
        db.commit()
        logging.info("Created default app: %s for user: %s", DEFAULT_APP_ID, USER_ID)
    except Exception as exc:
        logging.warning("Could not create default app: %s", exc)
    finally:
        db.close()


create_default_user()
create_default_app()

# Setup MCP server
setup_mcp_server(app)

# Include routers
app.include_router(memories_router)
app.include_router(apps_router)
app.include_router(stats_router)
app.include_router(config_router)
app.include_router(backup_router)

# Add pagination support
add_pagination(app)

logging.info("OpenMemory API started successfully (user_id=%s)", USER_ID)

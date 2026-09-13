import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from config import get_settings

settings = get_settings()

# In test environment, use SQLite. SQLITE_FILE (a filesystem path) selects a
# file-backed DB so a live uvicorn server and out-of-process seed scripts can
# share state (used by the Playwright golden-path E2E). Without it, an
# in-memory DB shared across connections via StaticPool is used (pytest).
if settings.environment == "test":
    _sqlite_file = os.environ.get("SQLITE_FILE")
    if _sqlite_file:
        engine = create_engine(
            f"sqlite:///{_sqlite_file}",
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )
    else:
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            pool_pre_ping=True,
        )
else:
    engine = create_engine(settings.database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    # Alembic owns schema in production; create_all only for dev/test convenience.
    if settings.environment == "production":
        return
    Base.metadata.create_all(bind=engine)

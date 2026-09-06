"""Shared pytest fixtures for LegacyLock backend tests.

Uses PostgreSQL test database (legacylock_test).
"""

import os

# Must be set before any application imports
os.environ["ENVIRONMENT"] = "test"
os.environ["SESSION_SECRET"] = "test-secret-key-for-testing-only-32b-0123456789"
os.environ["DATABASE_URL"] = "postgresql+psycopg://legacylock:legacylock@localhost:5432/legacylock_test"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:3000"
os.environ["HEARTBEAT_CHECK_INTERVAL"] = "999999"
os.environ["HEARTBEAT_ENABLED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from db import Base  # noqa: E402
from deps import get_db  # noqa: E402
from main import app  # noqa: E402
from models import User, Vault  # noqa: E402
from services.auth import hash_password, create_access_token  # noqa: E402

# PostgreSQL test database with NullPool (each test gets own connection)
_test_engine = create_engine(
    os.environ["DATABASE_URL"],
    poolclass=NullPool,
)

Base.metadata.create_all(bind=_test_engine)

_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)


def _override_get_db():
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(scope="session")
def client():
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture
def auth(client):
    """Create isolated user+vault and return owner auth headers (explicit role)."""
    db = _TestSession()
    try:
        import uuid

        email = f"test-{uuid.uuid4().hex[:8]}@example.com"
        user = User(email=email, password_hash=hash_password("TestPass123!Long"))
        db.add(user)
        db.commit()
        db.refresh(user)

        vault = Vault(user_id=user.id, name="Primary Vault")
        db.add(vault)
        db.commit()
        db.refresh(vault)

        access_token = create_access_token(user.id, vault.id, role="owner")
        return {"Authorization": f"Bearer {access_token}"}
    finally:
        db.close()


@pytest.fixture(autouse=True)
def clean_db():
    """Clean all tables before and after each test (full isolation)."""
    with _test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())

    yield

    with _test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())

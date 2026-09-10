"""Shared pytest fixtures for LegacyLock backend tests.

Uses SQLite in-memory database for testing.
"""

import os
import sys
from pathlib import Path

# Must be set before any application imports
os.environ["ENVIRONMENT"] = "test"
os.environ["SESSION_SECRET"] = "test-secret-key-for-testing-only-32b-0123456789"
os.environ["DATABASE_URL"] = "postgresql+psycopg://legacylock:legacylock@localhost:5432/legacylock_test"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:3000"
os.environ["HEARTBEAT_CHECK_INTERVAL"] = "999999"
os.environ["HEARTBEAT_ENABLED"] = "false"
# Use test RSA keys
test_keys_dir = Path(__file__).parent.parent / "keys"
os.environ["JWT_PRIVATE_KEY_PATH"] = str(test_keys_dir / "jwt_private.pem")
os.environ["JWT_PUBLIC_KEY_PATH"] = str(test_keys_dir / "jwt_public.pem")

# Add backend directory to Python path
BACKEND_DIR = Path(__file__).parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from db import Base, engine  # noqa: E402
from deps import get_db  # noqa: E402
from main import app  # noqa: E402
from models import User, Vault  # noqa: E402
from services.auth import create_access_token, hash_password  # noqa: E402

# Use the same engine as db.py (already configured for test environment)
Base.metadata.create_all(bind=engine)

_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


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
    # Clean tables first
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    # Then create fresh tables
    Base.metadata.create_all(bind=engine)

    yield

    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())

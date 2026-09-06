"""Shared pytest fixtures for LegacyLock backend tests.

Uses PostgreSQL test database (legacylock_test).
"""

import os

# Must be set before any application imports
os.environ["ENVIRONMENT"] = "test"
os.environ["SESSION_SECRET"] = "test-secret-key-for-testing-only-32b"
os.environ["DATABASE_URL"] = "postgresql+psycopg://legacylock:legacylock@localhost:5432/legacylock_test"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:3000"
os.environ["HEARTBEAT_CHECK_INTERVAL"] = "999999"

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
    """Login and return auth headers for test user."""
    # Create test user directly in DB
    from deps import get_db
    import jwt
    from datetime import UTC, datetime, timedelta
    
    db = next(get_db())
    try:
        # Check if test user already exists
        user = db.query(User).filter(User.email == "test@example.com").first()
        if not user:
            user = User(email="test@example.com", password_hash=hash_password("TestPass123!"))
            db.add(user)
            db.commit()
            db.refresh(user)
        
        # Check if vault exists for user
        vault = db.query(Vault).filter(Vault.user_id == user.id).first()
        if not vault:
            vault = Vault(user_id=user.id, name="Primary Vault")
            db.add(vault)
            db.commit()
            db.refresh(vault)
        
        # Use HS256 with a test secret for testing (instead of RS256 which needs RSA keys)
        payload = {
            "sub": str(user.id),
            "vault_id": vault.id,
            "type": "access",
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(minutes=15)).timestamp()),
        }
        access_token = jwt.encode(payload, "test-secret-key", algorithm="HS256")
        return {"Authorization": f"Bearer {access_token}"}
    finally:
        db.close()


@pytest.fixture(autouse=True)
def clean_db():
    """Clean all tables except user and vault before and after each test."""
    # Tables to preserve (created once per session by auth fixture)
    preserve_tables = {"user", "vault"}
    
    # Clean before test
    with _test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            if table.name not in preserve_tables:
                conn.execute(table.delete())
    
    yield
    
    # Clean after test
    with _test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            if table.name not in preserve_tables:
                conn.execute(table.delete())

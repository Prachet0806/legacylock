"""Shared pytest fixtures for LegacyLock backend tests.

Schema is built by Alembic (`alembic upgrade head`) on a file-backed SQLite
DB — never create_all — so model/migration drift fails loudly.
"""

import os
import sys
from pathlib import Path

# Must be set before any application imports
os.environ["ENVIRONMENT"] = "test"
os.environ["SESSION_SECRET"] = "test-secret-key-for-testing-only-32b-0123456789"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    ("postgresql+psycopg://legacylock:legacylock@localhost:5432/legacylock_test"),
)
os.environ["ALLOWED_ORIGINS"] = "http://localhost:3000"
os.environ["HEARTBEAT_CHECK_INTERVAL"] = "999999"
os.environ["HEARTBEAT_ENABLED"] = "false"
os.environ["REGISTRATION_INVITE_CODE"] = "test-invite-code-123"
os.environ["RESEND_API_KEY"] = ""
os.environ["EMAIL_VERIFICATION_TTL_HOURS"] = "24"
# Use test RSA keys
test_keys_dir = Path(__file__).parent.parent / "keys"
os.environ["JWT_PRIVATE_KEY_PATH"] = str(test_keys_dir / "jwt_private.pem")
os.environ["JWT_PUBLIC_KEY_PATH"] = str(test_keys_dir / "jwt_public.pem")

# Add backend directory to Python path
BACKEND_DIR = Path(__file__).parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# File-backed SQLite for the whole test session so Alembic (a separate
# engine) shares state with the app. Set BEFORE app imports.
# USE_POSTGRES=1 (CI parity job) keeps the real Postgres DATABASE_URL.
import tempfile as _tempfile  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

if os.environ.get("USE_POSTGRES") != "1":
    _tmp = _tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    _tmp.close()
    os.environ["SQLITE_FILE"] = _tmp.name
    os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"

from alembic.config import Config as _AlembicConfig  # noqa: E402

# Build test schema via migrations, not metadata reflection.
from alembic import command as _alembic_command  # noqa: E402
from db import Base, engine  # noqa: E402
from deps import get_db  # noqa: E402
from main import app  # noqa: E402
from models import User, Vault  # noqa: E402
from services.auth import hash_password  # noqa: E402


def _upgrade_test_schema() -> None:
    cfg = _AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    _alembic_command.upgrade(cfg, "head")


_upgrade_test_schema()

_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def prepare_release_ready_vault(vault_id: int | None = None) -> None:
    """Give release-flow tests explicit current ceremony, quorum and drill evidence."""
    import json
    import uuid
    from datetime import UTC, datetime
    from typing import Any, cast

    from models import Beneficiary, RecoveryCeremony
    from services.recovery_readiness import assignment_signature

    with _TestSession() as db:
        vault = (
            db.query(Vault).filter(Vault.id == vault_id).one()
            if vault_id
            else db.query(Vault).one()
        )
        generation = uuid.uuid4().hex
        typed_vault = cast(Any, vault)
        typed_vault.recovery_status = "READY"
        typed_vault.recovery_generation = generation
        typed_vault.recovery_threshold = 2
        typed_vault.recovery_total = 3
        ceremony = RecoveryCeremony(
            vault_id=vault.id,
            generation=generation,
            threshold=2,
            total=3,
            status="FINALIZED",
            expected_revision=max(0, int(vault.material_revision) - 1),
            acknowledgments="[1,2,3]",
        )
        db.add(ceremony)
        db.flush()
        for index in (1, 2):
            db.add(
                Beneficiary(
                    vault_id=vault.id,
                    name=f"Ready recipient {index}",
                    email=f"ready-recipient-{index}@example.com",
                    share_index=index,
                    ceremony_generation=generation,
                    invitation_status="accepted",
                )
            )
        db.flush()
        signature, _ = assignment_signature(db, vault)
        cast(Any, ceremony).drill_data = json.dumps(
            {
                "material_revision": vault.material_revision,
                "assignment_signature": signature,
                "generation": generation,
                "reported_at": datetime.now(UTC).isoformat(),
                "verifier": "owner_report",
            }
        )
        db.commit()


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
        from datetime import UTC, datetime

        email = f"test-{uuid.uuid4().hex[:8]}@example.com"
        user = User(
            email=email,
            password_hash=hash_password("TestPass123!Long"),
            email_verified_at=datetime.now(UTC),
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        import base64

        vault = Vault(
            user_id=user.id,
            name="Primary Vault",
            wrapped_vmk=base64.b64encode(b"v" * 40).decode(),
            vmk_crypto_version=1,
            vmk_kdf_algorithm="PBKDF2-SHA256",
            vmk_kdf_salt=base64.b64encode(b"s" * 16).decode(),
            vmk_kdf_parameters='{"iterations":600000}',
            material_revision=1,
            recovery_status="LEGACY",
        )
        db.add(vault)
        db.commit()
        db.refresh(vault)

        from services.sessions import issue

        access_token, _ = issue(db, "owner", user.id, vault.id)
        db.commit()
        return {"Authorization": f"Bearer {access_token}"}
    finally:
        db.close()


@pytest.fixture
def release_ready(auth: dict[str, str]) -> dict[str, str]:
    prepare_release_ready_vault()
    return auth


@pytest.fixture(autouse=True)
def clean_db():
    """Wipe all rows before and after each test (schema persists)."""
    from sqlalchemy import text

    is_pg = engine.dialect.name == "postgresql"

    def _wipe(conn):
        if is_pg:
            tables = ", ".join(
                conn.dialect.identifier_preparer.format_table(t)
                for t in reversed(Base.metadata.sorted_tables)
            )
            conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        else:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())

    with engine.begin() as conn:
        _wipe(conn)

    yield

    with engine.begin() as conn:
        _wipe(conn)

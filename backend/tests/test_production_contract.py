"""Production configuration and operational failure-path regressions."""

import base64
from pathlib import Path
from typing import cast
from urllib.parse import urlencode

import pytest
from _pytest.monkeypatch import MonkeyPatch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.pool import QueuePool

from config import Settings
from preflight import PreflightError, check


def _production_settings(**overrides: object) -> Settings:
    values = dict(
        environment="production",
        database_url="postgresql+psycopg://user:password@db.legacylock.test/vault",
        session_secret="s" * 32,
        release_hold=True,
        delivery_enabled=False,
        auth_epoch="production-epoch-2026-10-23",
        background_in_api=False,
        heartbeat_enabled=True,
        frontend_url="https://app.legacylock.test",
        allowed_origins="https://app.legacylock.test",
        allowed_hosts="api.legacylock.test",
        resend_api_key="re_fixture_only",
        notification_email_from="noreply@legacylock.test",
    )
    values.update(overrides)
    return Settings.model_validate(values)


def test_production_requires_explicit_release_configuration() -> None:
    settings = _production_settings()
    settings.validate_production()
    settings.model_fields_set.remove("release_hold")
    with pytest.raises(RuntimeError, match="release_hold"):
        settings.validate_production()


def test_demo_mode_requires_explicit_separate_api_loops() -> None:
    settings = _production_settings(task_mode="single_process_demo")
    settings.validate_production()
    settings.background_in_api = True
    with pytest.raises(RuntimeError, match="BACKGROUND_IN_API=false"):
        settings.validate_production()
    settings.background_in_api = False
    with pytest.raises(PreflightError, match="Separate worker is disabled"):
        check("worker", settings)


def test_demo_mode_requires_two_pool_connections_for_advisory_lock() -> None:
    settings = _production_settings(task_mode="single_process_demo", db_pool_size=1)
    with pytest.raises(RuntimeError, match="DB_POOL_SIZE >= 2"):
        settings.validate_production()


def test_login_drops_db_connection_during_hash_and_rechecks_password(
    client: TestClient, auth: dict[str, str], monkeypatch: MonkeyPatch,
) -> None:
    from db import SessionLocal, engine
    from models import User
    from routers import auth as auth_router

    with SessionLocal() as db:
        user = db.query(User).one()
        user_id, email = int(user.id), str(user.email)
    checked_out: list[int] = []

    def rotate_during_verify(password: str, password_hash: str) -> bool:
        checked_out.append(cast(QueuePool, engine.pool).checkedout())
        with SessionLocal() as db:
            db.query(User).filter_by(id=user_id).update({"password_hash": "rotated"})
            db.commit()
        return True

    monkeypatch.setattr(auth_router, "verify_password", rotate_during_verify)
    response = client.post(
        "/auth/login", json={"email": email, "password": "TestPass123!Long"}
    )
    assert response.status_code == 401
    assert checked_out == [0]
    assert "legacylock_owner_session" not in response.cookies


def test_production_api_requires_monitor_credential_without_requiring_it_on_worker() -> None:
    settings = _production_settings()
    settings.validate_production()  # the private worker has no operations endpoint
    with pytest.raises(RuntimeError, match="OPERATIONS_TOKEN"):
        settings.validate_production_api()
    settings.operations_token = "o" * 32
    settings.validate_production_api()


def test_worker_preflight_requires_verified_database_certificate_and_payload_key(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    certificate = tmp_path / "database-root.crt"
    url = "postgresql+psycopg://user:password@db.legacylock.test/vault?" + urlencode(
        {"sslmode": "verify-full", "sslrootcert": str(certificate)}
    )
    settings = _production_settings(
        database_url=url,
        delivery_payload_key=base64.b64encode(b"k" * 32).decode(),
    )
    with pytest.raises(PreflightError, match="certificate"):
        check("worker", settings)
    certificate.write_text("synthetic fixture")
    check("worker", settings)
    settings.database_url = (
        "postgresql+psycopg://user:password@db.legacylock.test/vault?sslmode=verify-full"
    )
    monkeypatch.setenv("PGSSLROOTCERT", str(certificate))
    check("worker", settings)
    settings.delivery_payload_key = "invalid"
    with pytest.raises(PreflightError, match="DELIVERY_PAYLOAD_KEY"):
        check("worker", settings)


def test_api_preflight_checks_matching_jwt_keys(tmp_path: Path) -> None:
    certificate = tmp_path / "database-root.crt"
    certificate.write_text("synthetic fixture")
    url = "postgresql+psycopg://user:password@db.legacylock.test/vault?" + urlencode(
        {"sslmode": "verify-full", "sslrootcert": str(certificate)}
    )
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    settings = _production_settings(
        database_url=url,
        delivery_payload_key=base64.b64encode(b"k" * 32).decode(),
        operations_token="o" * 32,
        jwt_private_key_b64=base64.b64encode(private_pem).decode(),
        jwt_public_key_b64=base64.b64encode(public_pem).decode(),
    )
    check("api", settings)
    settings.jwt_public_key_b64 = SecretStr("invalid")
    with pytest.raises(PreflightError, match="JWT"):
        check("api", settings)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("auth_epoch", "initial"),
        ("background_in_api", True),
        ("frontend_url", "http://localhost:3000"),
        ("allowed_hosts", "localhost"),
        ("allowed_hosts", "*.legacylock.test"),
        ("allowed_origins", "https://app.legacylock.test,https://preview.legacylock.test"),
    ],
)
def test_production_rejects_unsafe_values(field: str, value: object) -> None:
    with pytest.raises(RuntimeError):
        _production_settings(**{field: value}).validate_production()


def test_secret_store_jwt_pem_takes_precedence_over_file_path() -> None:
    settings = _production_settings(
        jwt_private_key_path="missing-private.pem",
        jwt_public_key_path="missing-public.pem",
        jwt_private_key_b64=base64.b64encode(b"private-pem").decode(),
        jwt_public_key_b64=base64.b64encode(b"public-pem").decode(),
    )
    assert settings.jwt_private_key() == "private-pem"
    assert settings.jwt_public_key() == "public-pem"


def test_malformed_secret_store_jwt_pem_fails_without_echoing_secret() -> None:
    settings = _production_settings(jwt_private_key_b64="invalid secret!")
    with pytest.raises(RuntimeError, match="Invalid base64-encoded JWT PEM") as error:
        settings.jwt_private_key()
    assert "invalid secret!" not in str(error.value)


def test_worker_checkpoint_failure_does_not_mask_original_error(
    monkeypatch: MonkeyPatch,
) -> None:
    import worker

    def fail_checkpoint(*_args: object) -> None:
        raise OSError("db down")

    monkeypatch.setattr(worker, "checkpoint", fail_checkpoint)
    worker._record_failure("checker", RuntimeError("original"))


def test_migration_accepts_percent_in_sqlite_path(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from alembic.config import Config

    from alembic import command

    path = tmp_path / "migration%credential.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path.as_posix()}")
    cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).parent.parent / "alembic"))
    command.upgrade(cfg, "head")
    assert path.exists()


def test_rate_limit_does_not_match_fake_login_path() -> None:
    from middleware.rate_limiter import RateLimiterMiddleware

    limiter = RateLimiterMiddleware(None)
    assert limiter._limits_for("/auth/login") == ((5, 60), "/auth/login")
    assert limiter._limits_for("/auth/loginanything") != ((5, 60), "/auth/login")
    assert limiter._limits_for("/auth/login/anything") != ((5, 60), "/auth/login")
    assert limiter._limits_for("/beneficiaries/17/invite") == (
        (10, 100),
        "/beneficiaries/{id}/invite",
    )
    assert limiter._limits_for("/beneficiaries/not-an-id/invite") != (
        (10, 100),
        "/beneficiaries/{id}/invite",
    )


def test_many_vault_login_requires_explicit_recipient_id(client: TestClient) -> None:
    from db import SessionLocal
    from models import Beneficiary, DeliveryJob, User, Vault

    with SessionLocal() as db:
        for index in range(11):
            owner = User(email=f"owner-{index}@example.com", password_hash="unused")
            db.add(owner)
            db.flush()
            vault = Vault(user_id=owner.id, name=f"Vault {index}")
            db.add(vault)
            db.flush()
            beneficiary = Beneficiary(
                vault_id=vault.id,
                name="Shared recipient",
                email="shared@example.com",
                invitation_status="accepted",
            )
            db.add(beneficiary)
            db.flush()
            recipient_id = beneficiary.id
        db.commit()
    generic = client.post("/access/login/request", json={"email": "shared@example.com"})
    assert generic.status_code == 200
    with SessionLocal() as db:
        assert db.query(DeliveryJob).count() == 0
    explicit = client.post(
        "/access/login/request",
        json={"email": "shared@example.com", "beneficiary_id": recipient_id},
    )
    assert explicit.status_code == 200
    assert explicit.json() == generic.json()
    with SessionLocal() as db:
        assert db.query(DeliveryJob).count() == 1

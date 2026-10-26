"""Production configuration and operational failure-path regressions."""

import base64
from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch
from fastapi.testclient import TestClient

from config import Settings


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
        sms_enabled=False,
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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("auth_epoch", "initial"),
        ("background_in_api", True),
        ("frontend_url", "http://localhost:3000"),
        ("allowed_hosts", "localhost"),
        ("allowed_hosts", "*.legacylock.test"),
        ("allowed_origins", "https://app.legacylock.test,https://preview.legacylock.test"),
        ("sms_enabled", True),
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

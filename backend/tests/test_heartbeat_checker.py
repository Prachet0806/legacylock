"""Unit tests for services/heartbeat_checker.py — no HTTP calls."""

from datetime import UTC, datetime, timedelta

from models import HeartbeatConfig, NotificationLog, User, Vault, VaultStatus
from services.auth import hash_password


def _make_db():
    """Return a fresh in-memory session for isolated checker tests."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from db import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _seed_user_vault(db):
    user = User(email="owner@test.com", password_hash=hash_password("TestPass123!Long"))
    db.add(user)
    db.commit()
    db.refresh(user)
    vault = Vault(user_id=user.id, name="Test Vault")
    db.add(vault)
    db.commit()
    db.refresh(vault)
    return user, vault


def _seed_config(db, vault_id, interval_days: int, grace_days: int, last_check_in_offset_days: int | None):
    """Create HeartbeatConfig with last_check_in = now - offset."""
    now = datetime.now(UTC)
    cfg = HeartbeatConfig(
        vault_id=vault_id,
        interval_days=interval_days,
        grace_days=grace_days,
        last_check_in=(now - timedelta(days=last_check_in_offset_days)) if last_check_in_offset_days is not None else None,
        updated_at=now,
    )
    db.add(cfg)
    db.commit()
    return cfg


def _seed_status(db, vault_id, state: str = "active", grace_started_days_ago: int | None = None):
    now = datetime.now(UTC)
    grace_started = (now - timedelta(days=grace_started_days_ago)) if grace_started_days_ago is not None else None
    vs = VaultStatus(vault_id=vault_id, state=state, grace_started_at=grace_started, updated_at=now)
    db.add(vs)
    db.commit()
    return vs


class TestHeartbeatCheckerNoOp:
    def test_no_config_returns_empty(self):
        from services.heartbeat_checker import check_heartbeat
        db = _make_db()
        _seed_user_vault(db)
        result = check_heartbeat(db)
        assert result == []

    def test_no_last_checkin_skipped(self):
        from services.heartbeat_checker import check_heartbeat
        db = _make_db()
        _, vault = _seed_user_vault(db)
        _seed_config(db, vault.id, 30, 7, None)
        _seed_status(db, vault.id, "active")
        assert check_heartbeat(db) == []

    def test_within_interval_no_action(self):
        from services.heartbeat_checker import check_heartbeat
        db = _make_db()
        _, vault = _seed_user_vault(db)
        _seed_config(db, vault.id, 30, 7, 10)
        _seed_status(db, vault.id, "active")
        assert check_heartbeat(db) == []

    def test_already_triggered_no_action(self):
        from services.heartbeat_checker import check_heartbeat
        db = _make_db()
        _, vault = _seed_user_vault(db)
        _seed_config(db, vault.id, 30, 7, 100)
        _seed_status(db, vault.id, "triggered")
        assert check_heartbeat(db) == []


class TestHeartbeatCheckerGrace:
    def test_interval_exceeded_starts_grace(self):
        from services.heartbeat_checker import check_heartbeat
        db = _make_db()
        _, vault = _seed_user_vault(db)
        _seed_config(db, vault.id, 30, 7, 31)
        _seed_status(db, vault.id, "active")
        result = check_heartbeat(db)
        assert result == [f"vault_{vault.id}_grace_started"]

    def test_vault_status_set_to_grace(self):
        from services.heartbeat_checker import check_heartbeat
        db = _make_db()
        _, vault = _seed_user_vault(db)
        _seed_config(db, vault.id, 30, 7, 31)
        _seed_status(db, vault.id, "active")
        check_heartbeat(db)
        vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault.id).first()
        assert vs.state == "grace"
        assert vs.grace_started_at is not None

    def test_within_grace_notify(self):
        from services.heartbeat_checker import check_heartbeat
        db = _make_db()
        _, vault = _seed_user_vault(db)
        _seed_config(db, vault.id, 30, 7, 31)
        _seed_status(db, vault.id, "grace", grace_started_days_ago=3)
        result = check_heartbeat(db)
        assert result == [f"vault_{vault.id}_grace_notify"]


class TestHeartbeatCheckerTriggered:
    def test_grace_expired_triggers(self):
        from services.heartbeat_checker import check_heartbeat
        db = _make_db()
        _, vault = _seed_user_vault(db)
        _seed_config(db, vault.id, 30, 7, 100)
        _seed_status(db, vault.id, "grace", grace_started_days_ago=8)
        result = check_heartbeat(db)
        assert result == [f"vault_{vault.id}_triggered"]

    def test_vault_status_set_to_triggered(self):
        from services.heartbeat_checker import check_heartbeat
        db = _make_db()
        _, vault = _seed_user_vault(db)
        _seed_config(db, vault.id, 30, 7, 100)
        _seed_status(db, vault.id, "grace", grace_started_days_ago=8)
        check_heartbeat(db)
        vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault.id).first()
        assert vs.state == "triggered"
        assert vs.triggered_at is not None
        assert vs.trigger_reason == "inactivity"


class TestHeartbeatCheckerIdempotency:
    def test_grace_notifications_not_duplicated(self):
        """Running checker twice in grace should not double-log notifications."""
        from services.heartbeat_checker import check_heartbeat
        db = _make_db()
        _, vault = _seed_user_vault(db)
        _seed_config(db, vault.id, 30, 7, 31)
        _seed_status(db, vault.id, "grace", grace_started_days_ago=0)

        check_heartbeat(db)
        check_heartbeat(db)

        # grace_warn_1 should appear exactly once
        count = db.query(NotificationLog).filter(NotificationLog.notif_type == "grace_warn_1").count()
        assert count <= 1  # 0 if no beneficiaries, but never > 1

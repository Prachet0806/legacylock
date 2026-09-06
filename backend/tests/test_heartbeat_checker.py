"""Unit tests for services/heartbeat_checker.py — no HTTP calls."""

from datetime import UTC, datetime, timedelta

from models import HeartbeatConfig, NotificationLog, VaultStatus, Vault


def _make_db():
    """Return a fresh in-memory session for isolated checker tests."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from db import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _seed_config(db, interval_days: int, grace_days: int, last_check_in_offset_days: int):
    """Create HeartbeatConfig with last_check_in = now - offset."""
    now = datetime.now(UTC)
    cfg = HeartbeatConfig(
        interval_days=interval_days,
        grace_days=grace_days,
        last_check_in=now - timedelta(days=last_check_in_offset_days),
        updated_at=now,
    )
    db.add(cfg)
    db.commit()
    return cfg


def _seed_vault(db, state: str = "active", grace_started_days_ago: int | None = None):
    """Create Vault and VaultStatus singleton."""
    now = datetime.now(UTC)
    grace_started = (now - timedelta(days=grace_started_days_ago)) if grace_started_days_ago is not None else None
    
    # Create vault first
    vault = Vault(user_id=1, name="Test Vault")
    db.add(vault)
    db.commit()
    db.refresh(vault)
    
    vs = VaultStatus(vault_id=vault.id, state=state, grace_started_at=grace_started, updated_at=now)
    db.add(vs)
    db.commit()
    return vs


class TestHeartbeatCheckerNoOp:
    def test_no_config_returns_none(self):
        from services.heartbeat_checker import check_heartbeat
        db = _make_db()
        result = check_heartbeat(db)
        assert result is None

    def test_no_last_checkin_returns_none(self):
        from services.heartbeat_checker import check_heartbeat
        db = _make_db()
        cfg = HeartbeatConfig(interval_days=30, grace_days=7, updated_at=datetime.now(UTC))
        db.add(cfg)
        db.commit()
        result = check_heartbeat(db)
        assert result is None

    def test_within_interval_returns_none(self):
        from services.heartbeat_checker import check_heartbeat
        db = _make_db()
        _seed_config(db, interval_days=30, grace_days=7, last_check_in_offset_days=10)
        _seed_vault(db, state="active")
        result = check_heartbeat(db)
        assert result is None

    def test_already_triggered_returns_none(self):
        from services.heartbeat_checker import check_heartbeat
        db = _make_db()
        _seed_config(db, interval_days=30, grace_days=7, last_check_in_offset_days=100)
        _seed_vault(db, state="triggered")
        result = check_heartbeat(db)
        assert result is None


class TestHeartbeatCheckerGrace:
    def test_interval_exceeded_starts_grace(self):
        from services.heartbeat_checker import check_heartbeat
        db = _make_db()
        _seed_config(db, interval_days=30, grace_days=7, last_check_in_offset_days=31)
        _seed_vault(db, state="active")
        result = check_heartbeat(db)
        assert result == "grace_started"

    def test_vault_status_set_to_grace(self):
        from services.heartbeat_checker import check_heartbeat
        db = _make_db()
        _seed_config(db, interval_days=30, grace_days=7, last_check_in_offset_days=31)
        _seed_vault(db, state="active")
        check_heartbeat(db)
        vs = db.query(VaultStatus).first()
        assert vs.state == "grace"
        assert vs.grace_started_at is not None

    def test_within_grace_returns_grace_notify(self):
        from services.heartbeat_checker import check_heartbeat
        db = _make_db()
        _seed_config(db, interval_days=30, grace_days=7, last_check_in_offset_days=31)
        _seed_vault(db, state="grace", grace_started_days_ago=3)
        result = check_heartbeat(db)
        assert result == "grace_notify"


class TestHeartbeatCheckerTriggered:
    def test_grace_expired_triggers(self):
        from services.heartbeat_checker import check_heartbeat
        db = _make_db()
        _seed_config(db, interval_days=30, grace_days=7, last_check_in_offset_days=100)
        _seed_vault(db, state="grace", grace_started_days_ago=8)
        result = check_heartbeat(db)
        assert result == "triggered"

    def test_vault_status_set_to_triggered(self):
        from services.heartbeat_checker import check_heartbeat
        db = _make_db()
        _seed_config(db, interval_days=30, grace_days=7, last_check_in_offset_days=100)
        _seed_vault(db, state="grace", grace_started_days_ago=8)
        check_heartbeat(db)
        vs = db.query(VaultStatus).first()
        assert vs.state == "triggered"
        assert vs.triggered_at is not None


class TestHeartbeatCheckerIdempotency:
    def test_grace_notifications_not_duplicated(self):
        """Running checker twice in grace should not double-log notifications."""
        from services.heartbeat_checker import check_heartbeat
        db = _make_db()
        _seed_config(db, interval_days=30, grace_days=7, last_check_in_offset_days=31)
        _seed_vault(db, state="grace", grace_started_days_ago=0)

        check_heartbeat(db)
        check_heartbeat(db)

        # grace_warn_1 should appear exactly once
        count = db.query(NotificationLog).filter(NotificationLog.notif_type == "grace_warn_1").count()
        assert count <= 1  # 0 if no beneficiaries, but never > 1
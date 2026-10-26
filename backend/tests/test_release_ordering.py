"""Both linearized check-in/release orderings on independent PostgreSQL transactions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

from db import SessionLocal, engine
from models import BusinessEvent, HeartbeatConfig, Vault, VaultStatus
from services.trigger_service import lock_status, trigger_vault

pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql", reason="Real row locks required"
)


def prepare():
    from tests.conftest import prepare_release_ready_vault

    prepare_release_ready_vault()
    with SessionLocal() as db:
        vid = db.query(Vault.id).scalar()
        db.add(
            VaultStatus(
                vault_id=vid,
                state="grace",
                armed=True,
                grace_started_at=datetime.now(UTC) - timedelta(days=2),
            )
        )
        db.add(
            HeartbeatConfig(
                vault_id=vid,
                interval_days=1,
                grace_days=1,
                last_check_in=datetime.now(UTC) - timedelta(days=3),
            )
        )
        db.commit()
        return vid


def test_checkin_commits_before_waiting_releaser(client, auth, monkeypatch):
    import routers.heartbeat as route

    vid = prepare()
    held, resume, trying = Event(), Event(), Event()
    original = route.lock_status

    def paused(db, vault_id):
        row = original(db, vault_id)
        held.set()
        assert resume.wait(10)
        return row

    monkeypatch.setattr(route, "lock_status", paused)

    def release():
        with SessionLocal() as db:
            db.query(HeartbeatConfig).filter_by(vault_id=vid).one()  # stale pre-lock observation
            trying.set()
            row, already = trigger_vault(db, vid, "inactivity")
            db.commit()
            return row.state, already

    with ThreadPoolExecutor(max_workers=2) as pool:
        checkin = pool.submit(client.post, "/heartbeat/checkin", headers=auth)
        assert held.wait(10)
        release_result = pool.submit(release)
        assert trying.wait(10)
        resume.set()
        assert checkin.result(timeout=15).status_code == 200
        assert release_result.result(timeout=15) == ("active", True)
    with SessionLocal() as db:
        assert db.query(BusinessEvent).filter_by(kind="released").count() == 0


def test_release_commits_before_waiting_checkin(client, auth, monkeypatch):
    import routers.heartbeat as route

    vid = prepare()
    attempting = Event()
    original = route.lock_status

    def waiting(db, vault_id):
        attempting.set()
        return original(db, vault_id)

    monkeypatch.setattr(route, "lock_status", waiting)
    with SessionLocal() as db, ThreadPoolExecutor(max_workers=1) as pool:
        lock_status(db, vid)
        checkin = pool.submit(client.post, "/heartbeat/checkin", headers=auth)
        assert attempting.wait(10)
        row, already = trigger_vault(db, vid, "inactivity")
        assert row.state == "triggered" and not already
        db.commit()
        assert checkin.result(timeout=15).status_code == 409
    with SessionLocal() as db:
        assert db.query(BusinessEvent).filter_by(kind="released").count() == 1

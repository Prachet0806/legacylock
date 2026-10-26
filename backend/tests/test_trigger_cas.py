"""CAS concurrency: exactly one authoritative transition wins.

Proves the heartbeat/trigger CAS contract from the deployment plan:
two workers racing ACTIVE→GRACE or GRACE→TRIGGERED produce exactly one
effective transition; the loser observes already_moved/already_triggered.
"""

from concurrent.futures import ThreadPoolExecutor


def _vault_id(client, auth):
    from db import SessionLocal
    from models import Vault

    db = SessionLocal()
    try:
        v = db.query(Vault).order_by(Vault.id.desc()).first()
        return v.id
    finally:
        db.close()


class TestTriggerCas:
    def test_double_trigger_is_idempotent(self, client, auth):
        from tests.conftest import prepare_release_ready_vault

        prepare_release_ready_vault()
        body = {"password": "TestPass123!Long", "confirm": True}
        first = client.post("/vault/trigger", json=body, headers=auth)
        assert first.status_code == 200
        assert first.json()["already"] is False
        second = client.post("/vault/trigger", json=body, headers=auth)
        assert second.status_code == 200
        assert second.json()["already"] is True

    def test_concurrent_move_to_grace_single_winner(self, client, auth):
        from tests.conftest import prepare_release_ready_vault

        prepare_release_ready_vault()
        from db import SessionLocal
        from services.trigger_service import move_to_grace

        vid = _vault_id(client, auth)
        assert vid is not None
        _arm_overdue(vid)

        def _attempt(_: int) -> bool:
            db = SessionLocal()
            try:
                _, already = move_to_grace(db, vid)
                db.commit()
                return already
            finally:
                db.close()

        with ThreadPoolExecutor(max_workers=2) as ex:
            results = list(ex.map(_attempt, range(2)))
        # Exactly one worker performed the transition; the other lost the CAS race.
        assert sorted(results) == [False, True]

    def test_concurrent_trigger_single_winner(self, client, auth):
        from tests.conftest import prepare_release_ready_vault

        prepare_release_ready_vault()
        from db import SessionLocal
        from services.trigger_service import move_to_grace, trigger_vault

        vid = _vault_id(client, auth)
        _arm_overdue(vid)
        db0 = SessionLocal()
        try:
            move_to_grace(db0, vid)
            db0.commit()
        finally:
            db0.close()

        def _attempt(_: int) -> bool:
            db = SessionLocal()
            try:
                _, already = trigger_vault(db, vid, reason="inactivity")
                db.commit()
                return already
            finally:
                db.close()

        with ThreadPoolExecutor(max_workers=2) as ex:
            results = list(ex.map(_attempt, range(2)))
        assert sorted(results) == [False, True]


def _arm_overdue(vid):
    from datetime import UTC, datetime, timedelta

    from db import SessionLocal
    from models import HeartbeatConfig
    from services.trigger_service import lock_status

    with SessionLocal() as db:
        row = lock_status(db, vid)
        row.armed = True
        cfg = HeartbeatConfig(
            vault_id=vid,
            interval_days=1,
            grace_days=1,
            last_check_in=datetime.now(UTC) - timedelta(days=3),
        )
        db.add(cfg)
        db.commit()

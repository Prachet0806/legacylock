"""The demo scheduler must never send an uncommitted outbox job."""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from _pytest.monkeypatch import MonkeyPatch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from config import get_settings
from db import SessionLocal, engine
from main import app
from models import DeliveryJob
from routers import health
from services import auth as auth_service
from services import demo_scheduler
from services.notifications import DeliveryResult
from services.outbox import claim, enqueue, event


def _queue(db: Session, suffix: str, kind: str = "verification") -> str:
    job = enqueue(
        db,
        event(db, None, kind, int(datetime.now(UTC).timestamp())),
        f"owner:{suffix}",
        f"{suffix}@example.com",
        "Verify",
        "Synthetic body",
    )
    return str(job.id)


def _job(db: Session, ident: str) -> DeliveryJob:
    row = db.get(DeliveryJob, ident)
    assert row is not None
    return row


def _wait_for_job(ident: str, expected: str = "ACCEPTED") -> None:
    for _ in range(100):
        with SessionLocal() as db:
            state = _job(db, ident).state
        if state == expected:
            return
        time.sleep(0.05)
    raise AssertionError(f"Job {ident} stayed in {state}, expected {expected}")


def test_delivery_signal_follows_outer_commit(monkeypatch: MonkeyPatch) -> None:
    signals = []
    monkeypatch.setattr(demo_scheduler, "signal_delivery", lambda: signals.append(True))
    with SessionLocal() as db:
        with db.begin():
            with db.begin_nested():
                ident = _queue(db, "nested")
            assert not signals
        assert signals == [True]
        assert db.get(DeliveryJob, ident) is not None


def test_delivery_rollback_never_signals(monkeypatch: MonkeyPatch) -> None:
    signals = []
    monkeypatch.setattr(demo_scheduler, "signal_delivery", lambda: signals.append(True))
    with SessionLocal() as db:
        _queue(db, "rolled-back")
        db.rollback()
    assert not signals


def test_rolled_back_savepoint_does_not_wake_scheduler(monkeypatch: MonkeyPatch) -> None:
    signals = []
    monkeypatch.setattr(demo_scheduler, "signal_delivery", lambda: signals.append(True))
    with SessionLocal() as db:
        with db.begin(), pytest.raises(RuntimeError, match="discard"), db.begin_nested():
            ident = _queue(db, "discarded-savepoint")
            raise RuntimeError("discard")
        assert db.get(DeliveryJob, ident) is None
    assert not signals


def test_outer_job_survives_rolled_back_savepoint(monkeypatch: MonkeyPatch) -> None:
    signals = []
    monkeypatch.setattr(demo_scheduler, "signal_delivery", lambda: signals.append(True))
    with SessionLocal() as db:
        with db.begin():
            ident = _queue(db, "outer-kept")
            with pytest.raises(RuntimeError, match="discard"), db.begin_nested():
                _queue(db, "inner-discarded")
                raise RuntimeError("discard")
        assert db.get(DeliveryJob, ident) is not None
    assert signals == [True]


def test_next_due_covers_retry_and_expired_lease() -> None:
    with SessionLocal() as db:
        first = _queue(db, "retry-due")
        second = _queue(db, "lease-due")
        db.flush()
        db.query(DeliveryJob).filter_by(id=first).update({
            "state": "RETRY_WAIT",
            "due_at": datetime.now(UTC) + timedelta(minutes=2),
        })
        db.query(DeliveryJob).filter_by(id=second).update({
            "state": "CLAIMED",
            "lease_until": datetime.now(UTC) + timedelta(minutes=1),
        })
        db.commit()
    due = demo_scheduler.DemoScheduler._next_delivery_due()
    assert due is not None
    assert timedelta(seconds=30) < due - datetime.now(UTC) < timedelta(minutes=2)


def test_next_due_skips_disabled_delivery_and_held_release(
    monkeypatch: MonkeyPatch,
) -> None:
    settings = get_settings()
    with SessionLocal() as db:
        _queue(db, "held-release", kind="released")
        db.commit()
    monkeypatch.setattr(settings, "release_hold", True)
    assert demo_scheduler.DemoScheduler._next_delivery_due() is None
    with SessionLocal() as db:
        _queue(db, "ordinary-verification")
        db.commit()
    assert demo_scheduler.DemoScheduler._next_delivery_due() is not None
    monkeypatch.setattr(settings, "delivery_enabled", False)
    assert demo_scheduler.DemoScheduler._next_delivery_due() is None


def test_startup_recovers_pending_job_and_due_retry() -> None:
    with SessionLocal() as db:
        pending = _queue(db, "startup-pending")
        retry = _queue(db, "startup-retry")
        db.flush()
        db.query(DeliveryJob).filter_by(id=retry).update({
            "state": "RETRY_WAIT",
            "due_at": datetime.now(UTC) + timedelta(seconds=1),
        })
        db.commit()

    async def run() -> None:
        scheduler = demo_scheduler.DemoScheduler()
        scheduler.start()
        try:
            for _ in range(80):
                with SessionLocal() as db:
                    states = [_job(db, ident).state for ident in (pending, retry)]
                if states == ["ACCEPTED", "ACCEPTED"]:
                    return
                await asyncio.sleep(0.05)
            raise AssertionError(f"Scheduler failed to recover pending work: {states}")
        finally:
            await scheduler.stop()

    asyncio.run(run())


def test_committed_job_wakes_idle_scheduler() -> None:
    async def run() -> None:
        scheduler = demo_scheduler.DemoScheduler()
        scheduler.start()
        try:
            for _ in range(80):
                if scheduler.last_delivery_at:
                    break
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("Initial delivery sweep did not finish")
            with SessionLocal() as db:
                ident = _queue(db, "commit-signal")
                db.commit()
            for _ in range(80):
                with SessionLocal() as db:
                    state = _job(db, ident).state
                if state == "ACCEPTED":
                    return
                await asyncio.sleep(0.05)
            raise AssertionError(f"Committed job was not signalled: {state}")
        finally:
            await scheduler.stop()

    asyncio.run(run())


def test_scheduler_health_distinguishes_idle_from_failed(
    monkeypatch: MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "task_mode", "single_process_demo")
    state = {
        "running": True,
        "last_heartbeat_at": datetime.now(UTC),
        "last_delivery_at": datetime.now(UTC),
        "errors": {},
    }
    monkeypatch.setattr(demo_scheduler, "scheduler_status", lambda: state)
    assert health.scheduler_health().status_code == 200
    state["errors"] = {"heartbeat": "OperationalError"}
    assert health.scheduler_health().status_code == 503
    state["errors"] = {}
    state["last_delivery_at"] = datetime.now(UTC) - timedelta(hours=2)
    assert health.scheduler_health().status_code == 503


def test_fastapi_lifespan_starts_and_stops_demo_scheduler(
    monkeypatch: MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "task_mode", "single_process_demo")
    monkeypatch.setattr(settings, "background_in_api", False)
    with TestClient(app) as client:
        for _ in range(80):
            response = client.get("/scheduler-health")
            if response.status_code == 200:
                break
            time.sleep(0.05)
        assert response.status_code == 200
        state = demo_scheduler.scheduler_status()
        assert state is not None and state["running"]
    assert demo_scheduler.scheduler_status() is None


def test_registration_commits_then_demo_scheduler_delivers(
    monkeypatch: MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "task_mode", "single_process_demo")
    monkeypatch.setattr(settings, "background_in_api", False)
    sent: list[str] = []

    async def accepted(to: str, *_args: str) -> DeliveryResult:
        sent.append(to)
        return DeliveryResult(True, provider_id="synthetic-provider")

    monkeypatch.setattr("services.notifications.deliver_email", accepted)
    email = f"demo-{uuid4().hex[:10]}@example.com"
    with TestClient(app) as client:
        response = client.post(
            "/auth/register",
            json={
                "email": email,
                "password": "RegisterPass123!Long",
                "invite_code": settings.registration_invite_code,
            },
        )
        assert response.status_code == 201
        with SessionLocal() as db:
            job = db.query(DeliveryJob).filter(DeliveryJob.recipient_key.like("owner:%")).one()
            ident = str(job.id)
        _wait_for_job(ident)
    assert sent == [email]


def test_invitation_commits_then_demo_scheduler_delivers(
    monkeypatch: MonkeyPatch, auth: dict[str, str],
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "task_mode", "single_process_demo")
    monkeypatch.setattr(settings, "background_in_api", False)
    sent: list[str] = []

    async def accepted(to: str, *_args: str) -> DeliveryResult:
        sent.append(to)
        return DeliveryResult(True, provider_id="synthetic-provider")

    monkeypatch.setattr("services.notifications.deliver_email", accepted)
    email = f"invite-{uuid4().hex[:10]}@example.com"
    with TestClient(app) as client:
        added = client.post(
            "/beneficiaries", json={"name": "Fixture", "email": email}, headers=auth
        )
        assert added.status_code == 201
        invited = client.post(f"/beneficiaries/{added.json()['id']}/invite", headers=auth)
        assert invited.status_code == 200
        with SessionLocal() as db:
            job = (
                db.query(DeliveryJob)
                .filter_by(recipient_key=f"beneficiary:{added.json()['id']}")
                .one()
            )
            ident = str(job.id)
        _wait_for_job(ident)
    assert sent == [email]


def test_startup_reclaims_expired_delivery_lease() -> None:
    with SessionLocal() as db:
        ident = _queue(db, "expired-startup-lease")
        db.commit()
        assert claim(db)
        db.query(DeliveryJob).filter_by(id=ident).update({
            "lease_until": datetime.now(UTC) - timedelta(seconds=1),
        })
        db.commit()

    async def run() -> None:
        scheduler = demo_scheduler.DemoScheduler()
        scheduler.start()
        try:
            for _ in range(100):
                with SessionLocal() as db:
                    state = _job(db, ident).state
                if state == "ACCEPTED":
                    return
                await asyncio.sleep(0.05)
            raise AssertionError(f"Expired lease was not reclaimed: {state}")
        finally:
            await scheduler.stop()

    asyncio.run(run())


def test_failed_heartbeat_pass_clears_error_after_recovery(
    monkeypatch: MonkeyPatch,
) -> None:
    original = demo_scheduler.DemoScheduler._heartbeat_pass
    calls = 0

    def flaky() -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic database failure")
        return original()

    monkeypatch.setattr(demo_scheduler.DemoScheduler, "_heartbeat_pass", staticmethod(flaky))

    async def run() -> None:
        scheduler = demo_scheduler.DemoScheduler()
        assert not await scheduler._run_pass("heartbeat")
        assert scheduler.status()["errors"] == {"heartbeat": "RuntimeError"}
        assert await scheduler._run_pass("heartbeat")
        assert scheduler.status()["errors"] == {}

    asyncio.run(run())


def test_demo_argon2_slot_limits_simultaneous_hashing(monkeypatch: MonkeyPatch) -> None:
    slots = threading.BoundedSemaphore(1)
    start = threading.Barrier(4)
    lock = threading.Lock()
    active = 0
    peak = 0

    def slow_hash(password: str) -> str:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return password

    monkeypatch.setattr(auth_service, "_hash_slots", slots)
    monkeypatch.setattr(auth_service, "ph", SimpleNamespace(hash=slow_hash))

    def hash_after_start(index: int) -> str:
        start.wait()
        return auth_service.hash_password(str(index))

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(hash_after_start, range(4))) == ["0", "1", "2", "3"]
    assert peak == 1


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostgreSQL required")
def test_postgres_advisory_lock_rejects_second_pass() -> None:
    with demo_scheduler._pass_lock() as first:
        assert first
        with demo_scheduler._pass_lock() as second:
            assert not second

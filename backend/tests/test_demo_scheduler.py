"""The demo scheduler must never send an uncommitted outbox job."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from _pytest.monkeypatch import MonkeyPatch
from sqlalchemy.orm import Session

from config import get_settings
from db import SessionLocal, engine
from models import DeliveryJob
from routers import health
from services import demo_scheduler
from services.outbox import enqueue, event


def _queue(db: Session, suffix: str, kind: str = "verification") -> str:
    job = enqueue(
        db,
        event(db, None, kind, int(datetime.now(UTC).timestamp())),
        f"owner:{suffix}",
        f"{suffix}@example.com",
        "Verify",
        "Synthetic body",
    )
    return job.id


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


def test_next_due_covers_retry_and_expired_lease() -> None:
    with SessionLocal() as db:
        first = _queue(db, "retry-due")
        second = _queue(db, "lease-due")
        db.flush()
        retry = db.get(DeliveryJob, first)
        retry.state = "RETRY_WAIT"
        retry.due_at = datetime.now(UTC) + timedelta(minutes=2)
        claimed = db.get(DeliveryJob, second)
        claimed.state = "CLAIMED"
        claimed.lease_until = datetime.now(UTC) + timedelta(minutes=1)
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
        db.get(DeliveryJob, retry).state = "RETRY_WAIT"
        db.get(DeliveryJob, retry).due_at = datetime.now(UTC) + timedelta(seconds=1)
        db.commit()

    async def run() -> None:
        scheduler = demo_scheduler.DemoScheduler()
        scheduler.start()
        try:
            for _ in range(80):
                with SessionLocal() as db:
                    states = [db.get(DeliveryJob, ident).state for ident in (pending, retry)]
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
                    state = db.get(DeliveryJob, ident).state
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


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostgreSQL required")
def test_postgres_advisory_lock_rejects_second_pass() -> None:
    with demo_scheduler._pass_lock() as first:
        assert first
        with demo_scheduler._pass_lock() as second:
            assert not second

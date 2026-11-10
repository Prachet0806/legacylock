"""One-process, recoverable scheduler for the selected Render Free deployment.

PostgreSQL remains authoritative. Signals only shorten delivery latency; the
startup and periodic sweeps recover missed signals, retries, and expired leases.
"""

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import Lock

from sqlalchemy import event, func, text
from sqlalchemy.orm import Session, SessionTransaction

from config import get_settings
from db import SessionLocal, engine
from models import DeliveryJob
from services.heartbeat_checker import check_heartbeat
from services.operations import checkpoint
from services.outbox import delivery_eligibility_filter, utc, work_once

logger = logging.getLogger("legacylock.demo_scheduler")
_LOCK_ID = 663928112
_scheduler = None
_scheduler_lock = Lock()


def signal_delivery() -> None:
    with _scheduler_lock:
        current = _scheduler
    if current is not None:
        current.signal()


def scheduler_status() -> dict | None:
    with _scheduler_lock:
        current = _scheduler
    return current.status() if current is not None else None


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    if session.in_nested_transaction():
        return
    if session.info.pop("legacylock_outbox_enqueued", None):
        signal_delivery()


@event.listens_for(Session, "after_soft_rollback")
def _after_rollback(session: Session, previous_transaction: SessionTransaction) -> None:
    if previous_transaction.parent is None:
        session.info.pop("legacylock_outbox_enqueued", None)
    else:
        session.info.get("legacylock_outbox_enqueued", set()).discard(previous_transaction)


@contextmanager
def _pass_lock() -> Iterator[bool]:
    """Prevent a rollout overlap from running two demo schedulers at once."""
    if engine.dialect.name != "postgresql":
        yield True
        return
    with engine.connect() as connection:
        acquired = bool(connection.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": _LOCK_ID}
        ).scalar())
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _LOCK_ID})


class DemoScheduler:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.loop = asyncio.get_running_loop()
        self.wake = asyncio.Event()
        self.task: asyncio.Task | None = None
        self.started_at = datetime.now(UTC)
        self.last_heartbeat_at: datetime | None = None
        self.last_delivery_at: datetime | None = None
        self.errors: dict[str, str] = {}

    def signal(self) -> None:
        self.loop.call_soon_threadsafe(self.wake.set)

    def start(self) -> None:
        global _scheduler
        with _scheduler_lock:
            if _scheduler is not None:
                raise RuntimeError("Demo scheduler is already running")
            _scheduler = self
        self.task = self.loop.create_task(self._run(), name="legacylock-demo-scheduler")

    async def stop(self) -> None:
        global _scheduler
        with _scheduler_lock:
            if _scheduler is self:
                _scheduler = None
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    def status(self) -> dict:
        return {
            "running": bool(self.task and not self.task.done()),
            "started_at": self.started_at,
            "last_heartbeat_at": self.last_heartbeat_at,
            "last_delivery_at": self.last_delivery_at,
            "errors": self.errors.copy(),
        }

    @staticmethod
    def _next_delivery_due() -> datetime | None:
        settings = get_settings()
        if not settings.delivery_enabled:
            return None
        with SessionLocal() as db:
            ready = db.query(func.min(DeliveryJob.due_at)).filter(
                delivery_eligibility_filter(db),
                DeliveryJob.state.in_(["READY", "RETRY_WAIT"])
            ).scalar()
            claimed = db.query(func.min(DeliveryJob.lease_until)).filter(
                delivery_eligibility_filter(db),
                DeliveryJob.state == "CLAIMED", DeliveryJob.lease_until.isnot(None)
            ).scalar()
        candidates = [utc(value) for value in (ready, claimed) if value is not None]
        return min(candidates) if candidates else None

    @staticmethod
    def _heartbeat_pass() -> bool:
        with _pass_lock() as acquired:
            if not acquired:
                return False
            with SessionLocal() as db:
                check_heartbeat(db)
            checkpoint(SessionLocal, "checker")
            return True

    def _delivery_pass(self) -> bool:
        with _pass_lock() as acquired:
            if not acquired:
                return False
            work_once(
                SessionLocal,
                limit=self.settings.demo_delivery_batch_size,
                concurrency=1,
            )
            checkpoint(SessionLocal, "delivery")
            return True

    async def _run_pass(self, kind: str) -> bool:
        try:
            ran = await asyncio.to_thread(
                self._heartbeat_pass if kind == "heartbeat" else self._delivery_pass
            )
            if ran:
                if kind == "heartbeat":
                    self.last_heartbeat_at = datetime.now(UTC)
                else:
                    self.last_delivery_at = datetime.now(UTC)
                self.errors.pop(kind, None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.errors[kind] = type(exc).__name__
            logger.exception("Demo %s pass failed", kind)
            try:
                await asyncio.to_thread(
                    checkpoint,
                    SessionLocal,
                    "checker" if kind == "heartbeat" else "delivery",
                    type(exc).__name__,
                )
            except Exception:
                logger.exception("Could not record demo scheduler failure")
            return False
        else:
            return ran

    async def _run(self) -> None:
        interval = self.settings.demo_check_interval_seconds
        heartbeat_ok = await self._run_pass("heartbeat")
        delivery_ok = await self._run_pass("delivery")
        next_heartbeat = self.loop.time() + (interval if heartbeat_ok else 60)
        next_sweep = self.loop.time() + (interval if delivery_ok else 60)
        delivery_defer = 0.0
        while True:
            try:
                due = await asyncio.to_thread(self._next_delivery_due)
                self.errors.pop("due", None)
                due_delay = (
                    max(0.0, (due - datetime.now(UTC)).total_seconds())
                    if due else float("inf")
                )
            except Exception as exc:
                self.errors["due"] = type(exc).__name__
                logger.exception("Could not read next delivery due time")
                due_delay = 60
            now = self.loop.time()
            timeout = min(
                next_heartbeat - now,
                next_sweep - now,
                max(due_delay, delivery_defer - now),
            )
            signalled = False
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=max(0.0, timeout))
                signalled = True
            except TimeoutError:
                pass
            self.wake.clear()
            now = self.loop.time()
            if now >= next_heartbeat:
                ran = await self._run_pass("heartbeat")
                next_heartbeat = self.loop.time() + (interval if ran else 60)
            if now >= next_sweep or (
                now >= delivery_defer and (signalled or due_delay <= timeout)
            ):
                ran = await self._run_pass("delivery")
                delivery_defer = 0.0 if ran else self.loop.time() + 60
                next_sweep = self.loop.time() + (interval if ran else 60)

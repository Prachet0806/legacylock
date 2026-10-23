"""Bounded heartbeat evaluation; network delivery belongs to the outbox worker."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import Interval, String, cast, func

from config import get_settings
from models import HeartbeatConfig, VaultStatus
from services.audit import record_audit
from services.outbox import utc
from services.trigger_service import lock_status, release_locked, stage_warning

logger = logging.getLogger("legacylock.checker")


def check_heartbeat(db, now=None, limit=100, vault_id=None):
    now = utc(now) if now else datetime.now(UTC)
    if get_settings().release_hold:
        return []
    query = (
        db.query(VaultStatus.vault_id)
        .join(HeartbeatConfig, HeartbeatConfig.vault_id == VaultStatus.vault_id)
        .filter(
            VaultStatus.armed.is_(True),
            VaultStatus.state.in_(["active", "grace"]),
            HeartbeatConfig.last_check_in.isnot(None),
        )
    )
    if db.bind.dialect.name == "postgresql":
        due = HeartbeatConfig.last_check_in + cast(
            cast(HeartbeatConfig.interval_days, String) + " days", Interval
        )
    else:
        due = func.datetime(
            HeartbeatConfig.last_check_in, func.printf("+%d days", HeartbeatConfig.interval_days)
        )
    query = query.filter(due <= now)
    if vault_id is not None:
        query = query.filter(VaultStatus.vault_id == vault_id)
    ids = query.order_by(VaultStatus.updated_at, VaultStatus.vault_id).limit(min(limit, 1000)).all()
    actions = []
    failed = 0
    for (ident,) in ids:
        try:
            vs = lock_status(db, ident)
            cfg = db.query(HeartbeatConfig).filter_by(vault_id=ident).populate_existing().one()
            deadline = utc(cfg.last_check_in) + timedelta(days=cfg.interval_days)
            if not vs.armed or vs.state == "triggered" or now < deadline:
                db.rollback()
                continue
            if vs.state == "active":
                vs.state, vs.grace_started_at, vs.updated_at = "grace", deadline, now
                vs.episode += 1
                record_audit(db, ident, "system", 0, "heartbeat.grace", {"episode": vs.episode})
                actions.append(f"vault_{ident}_grace_started")
            if now >= deadline + timedelta(days=cfg.grace_days):
                release_locked(db, vs, "inactivity", now)
                actions.append(f"vault_{ident}_triggered")
            else:
                stage_warning(db, vs, cfg, now)
                actions.append(f"vault_{ident}_grace_notify")
            vs.updated_at = now
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Heartbeat evaluation failed for vault %s", ident)
            failed += 1
    if failed:
        raise RuntimeError(f"Heartbeat evaluation failed for {failed} vault(s)")
    return actions


def retry_failed_notifications(db, limit=20):
    from db import SessionLocal
    from services.outbox import work_once

    return work_once(SessionLocal, limit)

"""Heartbeat checker — evaluates inactivity and transitions vault status.

Call `check_heartbeat(db)` periodically (e.g. every hour) to:
1. Detect missed check-ins → move vault from 'active' to 'grace'
2. Detect expired grace period → move vault from 'grace' to 'triggered'
3. Send escalating notifications during grace period
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from models import Beneficiary, HeartbeatConfig, NotificationLog, Vault, VaultStatus

logger = logging.getLogger("legacylock.heartbeat")


def _utc(dt: datetime) -> datetime:
    """Ensure a datetime is UTC-aware. SQLite may return naive datetimes."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _elapsed_days(since: datetime, now: datetime) -> float:
    return (_utc(now) - _utc(since)).total_seconds() / 86400.0


def _schedule_coro(coro) -> None:
    """Best-effort in-process scheduling that never crashes sync callers.

    If a loop is running (uvicorn heartbeat task), schedule on it.
    Otherwise (tests/CLI), run inline to completion.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        try:
            loop.create_task(coro)
            return
        except RuntimeError:
            pass
    try:
        asyncio.run(coro)
    except RuntimeError:
        # Already in a loop edge-case: fall back to fire-and-forget via new loop
        try:
            import threading

            def _runner() -> None:
                try:
                    asyncio.run(coro)
                except Exception:
                    logger.exception("Background notification failed")

            threading.Thread(target=_runner, daemon=True).start()
        except Exception:
            logger.exception("Background notification failed")
    except Exception:
        logger.exception("Background notification failed")


def _get_vaults(db: Session) -> list[Vault]:
    """Get all vaults that have heartbeat configured."""
    return db.query(Vault).join(HeartbeatConfig).all()


def _get_vault_status(db: Session, vault_id: int) -> VaultStatus:
    vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault_id).first()
    if not vs:
        vs = VaultStatus(vault_id=vault_id, state="active")
        db.add(vs)
        try:
            db.commit()
        except Exception:
            db.rollback()
            vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault_id).first()
            if not vs:
                raise
            return vs
        db.refresh(vs)
    return vs


def _has_notification(
    db: Session, vault_id: int, notif_type: str, beneficiary_id: int | None = None
) -> bool:
    """Check if a notification of a given type has already been recorded."""
    query = db.query(NotificationLog).filter(
        NotificationLog.vault_id == vault_id,
        NotificationLog.notif_type == notif_type,
    )
    if beneficiary_id:
        query = query.filter(NotificationLog.beneficiary_id == beneficiary_id)
    return query.first() is not None


def _mark_notification(log_id: int, status: str) -> None:
    """Mark a notification row SENT/FAILED on a fresh session (thread-safe)."""
    from db import SessionLocal

    db = SessionLocal()
    try:
        row = db.query(NotificationLog).filter(NotificationLog.id == log_id).first()
        if row:
            row.status = status
            db.commit()
    finally:
        db.close()


def _dispatch(
    channel: str,
    send_coro,
    db: Session,
    vault_id: int,
    notif_type: str,
    beneficiary_id: int | None = None,
) -> None:
    """Record PENDING, schedule the send, mark SENT/FAILED on its real result.

    The DB unique constraint on (vault_id, beneficiary_id, type, channel) is
    the dedup authority; the _has_notification pre-check is only a fast path.
    """
    row = NotificationLog(
        vault_id=vault_id,
        beneficiary_id=beneficiary_id,
        channel=channel,
        notif_type=notif_type,
        status="pending",
    )
    db.add(row)
    try:
        db.commit()
    except Exception:
        # Lost the dedup race: another worker recorded it first.
        db.rollback()
        return
    db.refresh(row)
    log_id = row.id

    async def _run() -> None:
        try:
            ok = await send_coro
        except Exception:
            logger.exception("Background notification failed")
            ok = False
        _mark_notification(log_id, "sent" if ok else "failed")

    _schedule_coro(_run())


def _send_grace_notifications(
    db: Session, vault_id: int, cfg: HeartbeatConfig, vs: VaultStatus
) -> None:
    """Send escalating notifications during grace period."""
    from services.notifications import send_email, send_sms

    if not vs.grace_started_at:
        return
    now = datetime.now(UTC)
    grace_elapsed = _elapsed_days(vs.grace_started_at, now)
    beneficiaries = db.query(Beneficiary).filter(Beneficiary.vault_id == vault_id).all()
    if not beneficiaries:
        return

    # Day 0+: First warning (once)
    if grace_elapsed >= 0 and not _has_notification(db, vault_id, "grace_warn_1"):
        for b in beneficiaries:
            _dispatch(
                "email",
                send_email(
                    b.email,
                    "LegacyLock — Inactivity Warning",
                    f"The vault owner has missed their {cfg.interval_days}-day check-in. "
                    f"If they do not check in within {cfg.grace_days} days, vault access will be released.",
                ),
                db,
                vault_id,
                "grace_warn_1",
                b.id,
            )
        logger.info("Sent grace_warn_1 to %d beneficiaries", len(beneficiaries))

    # Day 3+: Second warning (once, only if grace period long enough)
    if (
        grace_elapsed >= 3
        and cfg.grace_days > 3
        and not _has_notification(db, vault_id, "grace_warn_2")
    ):
        for b in beneficiaries:
            remaining = max(0, cfg.grace_days - int(grace_elapsed))
            _dispatch(
                "email",
                send_email(
                    b.email,
                    "LegacyLock — Vault Release Approaching",
                    f"The vault owner has been inactive for {cfg.interval_days + int(grace_elapsed)} days. "
                    f"Release will occur in {remaining} days.",
                ),
                db,
                vault_id,
                "grace_warn_2",
                b.id,
            )
        logger.info("Sent grace_warn_2 to %d beneficiaries", len(beneficiaries))

    # Final 24h warning (once)
    if grace_elapsed >= max(0, cfg.grace_days - 1) and not _has_notification(
        db, vault_id, "final_warn"
    ):
        for b in beneficiaries:
            _dispatch(
                "email",
                send_email(
                    b.email,
                    "LegacyLock — FINAL WARNING — Vault Releasing Soon",
                    "The vault will be released within 24 hours. "
                    "If the owner does not check in, you will receive your access share.",
                ),
                db,
                vault_id,
                "final_warn",
                b.id,
            )
            # Also send SMS if phone is available
            if b.phone:
                _dispatch(
                    "sms",
                    send_sms(
                        b.phone,
                        "LegacyLock: Vault releasing in 24 hours. Check your email for details.",
                    ),
                    db,
                    vault_id,
                    "final_warn",
                    b.id,
                )
        logger.info("Sent final_warn to %d beneficiaries", len(beneficiaries))


def _send_trigger_notifications(db: Session, vault_id: int) -> None:
    """Notify all beneficiaries that the vault has been triggered."""
    from services.notifications import send_email, send_sms

    beneficiaries = db.query(Beneficiary).filter(Beneficiary.vault_id == vault_id).all()
    if not beneficiaries:
        return
    for b in beneficiaries:
        if not _has_notification(db, vault_id, f"triggered_{b.id}", b.id):
            _dispatch(
                "email",
                send_email(
                    b.email,
                    "LegacyLock — Vault Access Released",
                    "The vault owner's inactivity period has expired. "
                    "You have been granted access to the vault. "
                    "Please visit LegacyLock to enter your access share.",
                ),
                db,
                vault_id,
                f"triggered_{b.id}",
                b.id,
            )
            if b.phone:
                _dispatch(
                    "sms",
                    send_sms(
                        b.phone, "LegacyLock: Vault access has been released. Check your email."
                    ),
                    db,
                    vault_id,
                    f"triggered_sms_{b.id}",
                    b.id,
                )
    logger.info("Sent trigger notifications to %d beneficiaries", len(beneficiaries))


def check_heartbeat(db: Session) -> list[str]:
    """Evaluate heartbeat for all vaults and transition vault status.

    Returns:
        List of actions taken across all vaults.
    """
    vaults = _get_vaults(db)
    actions = []

    for vault in vaults:
        cfg = vault.heartbeat_config
        if not cfg or not cfg.last_check_in:
            continue  # heartbeat not configured or never checked in for this vault

        vs = _get_vault_status(db, vault.id)
        now = datetime.now(UTC)

        # Already triggered — nothing to do
        if vs.state == "triggered":
            continue

        deadline = _utc(cfg.last_check_in) + timedelta(days=cfg.interval_days)

        # Active → Grace
        if vs.state == "active" and now > deadline:
            from services.trigger_service import move_to_grace

            move_to_grace(db, vault.id)
            try:
                from services.audit import record_audit

                record_audit(db, vault.id, "system", 0, "heartbeat.grace", {"reason": "inactivity"})
                db.commit()
            except Exception:
                db.rollback()
            _send_grace_notifications(db, vault.id, cfg, vs)
            actions.append(f"vault_{vault.id}_grace_started")
            continue

        # Grace — send escalating notifications
        if vs.state == "grace" and vs.grace_started_at:
            grace_end = _utc(vs.grace_started_at) + timedelta(days=cfg.grace_days)

            if now > grace_end:
                # Grace → Triggered
                from services.trigger_service import trigger_vault as _auto_trigger

                _auto_trigger(db, vault.id, reason="inactivity")
                try:
                    from services.audit import record_audit

                    record_audit(
                        db, vault.id, "system", 0, "vault.trigger", {"reason": "inactivity"}
                    )
                    db.commit()
                except Exception:
                    db.rollback()
                _send_trigger_notifications(db, vault.id)
                actions.append(f"vault_{vault.id}_triggered")
            else:
                # Still in grace — check for notification milestones
                _send_grace_notifications(db, vault.id, cfg, vs)
                actions.append(f"vault_{vault.id}_grace_notify")

    return actions

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

from models import AccessRequest, Beneficiary, HeartbeatConfig, NotificationLog, Vault, VaultStatus

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


def _has_notification(db: Session, vault_id: int, notif_type: str, beneficiary_id: int | None = None) -> bool:
    """Check if a notification of a given type has already been sent."""
    query = db.query(NotificationLog).filter(
        NotificationLog.vault_id == vault_id,
        NotificationLog.notif_type == notif_type,
    )
    if beneficiary_id:
        query = query.filter(NotificationLog.beneficiary_id == beneficiary_id)
    return query.first() is not None


def _log_notification(
    db: Session,
    vault_id: int,
    notif_type: str,
    recipient: str,
    channel: str,
    beneficiary_id: int | None = None,
) -> None:
    db.add(NotificationLog(
        vault_id=vault_id,
        beneficiary_id=beneficiary_id,
        channel=channel,
        notif_type=notif_type,
        status="sent",
    ))
    db.commit()


def _auto_approve_access_requests_sync(db: Session, vault_id: int) -> int:
    """Auto-approve all pending access requests (sync, in-process). Returns count."""
    from services.notifications import send_email

    pending_requests = db.query(AccessRequest).filter(
        AccessRequest.vault_id == vault_id,
        AccessRequest.status == "pending"
    ).all()

    for req in pending_requests:
        req.status = "approved"
        req.approved_at = datetime.now(UTC)
        req.expires_at = datetime.now(UTC) + timedelta(days=30)
        try:
            email = req.beneficiary.email if req.beneficiary else None
        except Exception:
            email = None
        if email:
            _schedule_coro(
                send_email(
                    email,
                    "LegacyLock — Access Granted (Vault Triggered)",
                    "The vault has been triggered. Your access request has been automatically approved. "
                    "You can now submit your share to reconstruct the vault key.",
                )
            )

    if pending_requests:
        db.commit()
    return len(pending_requests)


async def _auto_approve_access_requests(db: Session, vault_id: int) -> None:
    """Async wrapper (legacy). Delegates to sync version."""
    _auto_approve_access_requests_sync(db, vault_id)


def _send_grace_notifications(db: Session, vault_id: int, cfg: HeartbeatConfig, vs: VaultStatus) -> None:
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
            _schedule_coro(
                send_email(
                    b.email,
                    "LegacyLock — Inactivity Warning",
                    f"The vault owner has missed their {cfg.interval_days}-day check-in. "
                    f"If they do not check in within {cfg.grace_days} days, vault access will be released.",
                )
            )
            _log_notification(db, vault_id, "grace_warn_1", b.email, "email", b.id)
        logger.info("Sent grace_warn_1 to %d beneficiaries", len(beneficiaries))

    # Day 3+: Second warning (once, only if grace period long enough)
    if grace_elapsed >= 3 and cfg.grace_days > 3 and not _has_notification(db, vault_id, "grace_warn_2"):
        for b in beneficiaries:
            remaining = max(0, cfg.grace_days - int(grace_elapsed))
            _schedule_coro(
                send_email(
                    b.email,
                    "LegacyLock — Vault Release Approaching",
                    f"The vault owner has been inactive for {cfg.interval_days + int(grace_elapsed)} days. "
                    f"Release will occur in {remaining} days.",
                )
            )
            _log_notification(db, vault_id, "grace_warn_2", b.email, "email", b.id)
        logger.info("Sent grace_warn_2 to %d beneficiaries", len(beneficiaries))

    # Final 24h warning (once)
    if grace_elapsed >= max(0, cfg.grace_days - 1) and not _has_notification(db, vault_id, "final_warn"):
        for b in beneficiaries:
            _schedule_coro(
                send_email(
                    b.email,
                    "LegacyLock — FINAL WARNING — Vault Releasing Soon",
                    "The vault will be released within 24 hours. "
                    "If the owner does not check in, you will receive your access share.",
                )
            )
            _log_notification(db, vault_id, "final_warn", b.email, "email", b.id)
            # Also send SMS if phone is available
            if b.phone:
                _schedule_coro(
                    send_sms(b.phone, "LegacyLock: Vault releasing in 24 hours. Check your email for details.")
                )
                _log_notification(db, vault_id, "final_warn", b.phone, "sms", b.id)
        logger.info("Sent final_warn to %d beneficiaries", len(beneficiaries))


def _send_trigger_notifications(db: Session, vault_id: int) -> None:
    """Notify all beneficiaries that the vault has been triggered."""
    from services.notifications import send_email, send_sms

    beneficiaries = db.query(Beneficiary).filter(Beneficiary.vault_id == vault_id).all()
    if not beneficiaries:
        return
    for b in beneficiaries:
        if not _has_notification(db, vault_id, f"triggered_{b.id}", b.id):
            _schedule_coro(
                send_email(
                    b.email,
                    "LegacyLock — Vault Access Released",
                    "The vault owner's inactivity period has expired. "
                    "You have been granted access to the vault. "
                    "Please visit LegacyLock to enter your access share.",
                )
            )
            _log_notification(db, vault_id, f"triggered_{b.id}", b.email, "email", b.id)
            if b.phone:
                _schedule_coro(
                    send_sms(b.phone, "LegacyLock: Vault access has been released. Check your email.")
                )
                _log_notification(db, vault_id, f"triggered_sms_{b.id}", b.phone, "sms", b.id)
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
            vs.state = "grace"
            vs.grace_started_at = now
            vs.version = (vs.version or 1) + 1
            vs.updated_at = now
            db.commit()
            _send_grace_notifications(db, vault.id, cfg, vs)
            actions.append(f"vault_{vault.id}_grace_started")
            continue

        # Grace — send escalating notifications
        if vs.state == "grace" and vs.grace_started_at:
            grace_end = _utc(vs.grace_started_at) + timedelta(days=cfg.grace_days)

            if now > grace_end:
                # Grace → Triggered
                vs.state = "triggered"
                vs.triggered_at = now
                vs.trigger_reason = "inactivity"
                vs.version = (vs.version or 1) + 1
                vs.updated_at = now
                db.commit()
                _send_trigger_notifications(db, vault.id)
                # Auto-approve access requests (sync, in-process)
                _auto_approve_access_requests_sync(db, vault.id)
                actions.append(f"vault_{vault.id}_triggered")
            else:
                # Still in grace — check for notification milestones
                _send_grace_notifications(db, vault.id, cfg, vs)
                actions.append(f"vault_{vault.id}_grace_notify")

    return actions
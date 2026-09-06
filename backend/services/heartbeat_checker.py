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


def _get_vault(db: Session) -> Vault:
    """Get the vault (assuming single vault)."""
    vault = db.query(Vault).first()
    if not vault:
        raise ValueError("Vault not found")
    return vault


def _get_vault_status(db: Session) -> VaultStatus:
    vault = _get_vault(db)
    vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault.id).first()
    if not vs:
        vs = VaultStatus(vault_id=vault.id, state="active")
        db.add(vs)
        db.commit()
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


async def _auto_approve_access_requests(db: Session, vault_id: int) -> None:
    """Auto-approve all pending access requests when vault is triggered."""
    from services.notifications import send_email
    
    pending_requests = db.query(AccessRequest).filter(
        AccessRequest.vault_id == vault_id,
        AccessRequest.status == "pending"
    ).all()
    
    for req in pending_requests:
        req.status = "approved"
        req.approved_at = datetime.now(UTC)
        req.expires_at = datetime.now(UTC) + timedelta(days=30)
        
        # Notify beneficiary
        asyncio.get_event_loop().create_task(
            send_email(
                req.beneficiary.email,
                "LegacyLock — Access Granted (Vault Triggered)",
                f"The vault has been triggered. Your access request has been automatically approved. "
                f"You can now submit your share to reconstruct the vault key.",
            )
        )
    
    if pending_requests:
        db.commit()


def _send_grace_notifications(db: Session, vault_id: int, cfg: HeartbeatConfig, vs: VaultStatus) -> None:
    """Send escalating notifications during grace period."""
    from services.notifications import send_email, send_sms

    now = datetime.now(UTC)
    grace_elapsed = (now - _utc(vs.grace_started_at)).days
    beneficiaries = db.query(Beneficiary).filter(Beneficiary.vault_id == vault_id).all()

    # Day 0–1: First warning to user
    if grace_elapsed >= 0 and not _has_notification(db, vault_id, "grace_warn_1"):
        for b in beneficiaries:
            asyncio.get_event_loop().create_task(
                send_email(
                    b.email,
                    "LegacyLock — Inactivity Warning",
                    f"The vault owner has missed their {cfg.interval_days}-day check-in. "
                    f"If they do not check in within {cfg.grace_days} days, vault access will be released.",
                )
            )
            _log_notification(db, vault_id, "grace_warn_1", b.email, "email", b.id)
        logger.info("Sent grace_warn_1 to %d beneficiaries", len(beneficiaries))

    # Day 3: Second warning
    if grace_elapsed >= 3 and not _has_notification(db, vault_id, "grace_warn_2"):
        for b in beneficiaries:
            asyncio.get_event_loop().create_task(
                send_email(
                    b.email,
                    "LegacyLock — Vault Release Approaching",
                    f"The vault owner has been inactive for {cfg.interval_days + grace_elapsed} days. "
                    f"Release will occur in {cfg.grace_days - grace_elapsed} days.",
                )
            )
            _log_notification(db, vault_id, "grace_warn_2", b.email, "email", b.id)
        logger.info("Sent grace_warn_2 to %d beneficiaries", len(beneficiaries))

    # Grace - 1 day: Final warning
    if grace_elapsed >= cfg.grace_days - 1 and not _has_notification(db, vault_id, "final_warn"):
        for b in beneficiaries:
            asyncio.get_event_loop().create_task(
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
                asyncio.get_event_loop().create_task(
                    send_sms(b.phone, "LegacyLock: Vault releasing in 24 hours. Check your email for details.")
                )
                _log_notification(db, vault_id, "final_warn", b.phone, "sms", b.id)
        logger.info("Sent final_warn to %d beneficiaries", len(beneficiaries))


def _send_trigger_notifications(db: Session, vault_id: int) -> None:
    """Notify all beneficiaries that the vault has been triggered."""
    from services.notifications import send_email, send_sms

    beneficiaries = db.query(Beneficiary).filter(Beneficiary.vault_id == vault_id).all()
    for b in beneficiaries:
        if not _has_notification(db, vault_id, f"triggered_{b.id}", b.id):
            asyncio.get_event_loop().create_task(
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
                asyncio.get_event_loop().create_task(
                    send_sms(b.phone, "LegacyLock: Vault access has been released. Check your email.")
                )
                _log_notification(db, vault_id, f"triggered_sms_{b.id}", b.phone, "sms", b.id)
        logger.info("Sent trigger notifications to %d beneficiaries", len(beneficiaries))


def check_heartbeat(db: Session) -> str | None:
    """Evaluate heartbeat and transition vault status.

    Returns:
        None            — no action needed
        'grace_started' — interval expired, grace period began
        'grace_notify'  — in grace period, sent notifications
        'triggered'     — grace period expired, vault triggered
    """
    cfg = db.query(HeartbeatConfig).first()
    if not cfg or not cfg.last_check_in:
        return None  # heartbeat not configured or never checked in

    vault = _get_vault(db)
    vs = _get_vault_status(db)
    now = datetime.now(UTC)

    # Already triggered — nothing to do
    if vs.state == "triggered":
        return None

    deadline = _utc(cfg.last_check_in) + timedelta(days=cfg.interval_days)

    # Active → Grace
    if vs.state == "active" and now > deadline:
        vs.state = "grace"
        vs.grace_started_at = now
        vs.updated_at = now
        db.commit()
        _send_grace_notifications(db, vault.id, cfg, vs)
        return "grace_started"

    # Grace — send escalating notifications
    if vs.state == "grace" and vs.grace_started_at:
        grace_end = _utc(vs.grace_started_at) + timedelta(days=cfg.grace_days)

        if now > grace_end:
            # Grace → Triggered
            vs.state = "triggered"
            vs.triggered_at = now
            vs.updated_at = now
            db.commit()
            _send_trigger_notifications(db, vault.id)
            # Auto-approve access requests
            import asyncio
            asyncio.get_event_loop().create_task(_auto_approve_access_requests(db, vault.id))
            return "triggered"
        else:
            # Still in grace — check for notification milestones
            _send_grace_notifications(db, vault.id, cfg, vs)
            return "grace_notify"

    return None
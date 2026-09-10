"""Trigger service — sole owner of ACTIVE->GRACE->TRIGGERED transitions.

Both manual (router) and automatic (heartbeat_checker) paths delegate here so
the transition is atomic and idempotent: repeated triggers are a no-op success.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from models import VaultStatus


def trigger_vault(db: Session, vault_id: int, reason: str) -> tuple[VaultStatus, bool]:
    """Atomically transition vault to triggered. Returns (status, already_triggered)."""
    vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault_id).first()
    if not vs:
        vs = VaultStatus(vault_id=vault_id, state="active")
        db.add(vs)
        db.commit()
        db.refresh(vs)
    if vs.state == "triggered":
        return vs, True
    now = datetime.now(UTC)
    vs.state = "triggered"
    vs.triggered_at = now
    vs.trigger_reason = reason
    vs.version = (vs.version or 1) + 1
    vs.updated_at = now
    db.commit()
    db.refresh(vs)
    return vs, False


def move_to_grace(db: Session, vault_id: int) -> tuple[VaultStatus, bool]:
    """Atomically transition vault active->grace. Returns (status, already_in_grace)."""
    vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault_id).first()
    if not vs:
        vs = VaultStatus(vault_id=vault_id, state="active")
        db.add(vs)
        db.commit()
        db.refresh(vs)
    if vs.state != "active":
        return vs, True
    now = datetime.now(UTC)
    vs.state = "grace"
    vs.grace_started_at = now
    vs.version = (vs.version or 1) + 1
    vs.updated_at = now
    db.commit()
    db.refresh(vs)
    return vs, False

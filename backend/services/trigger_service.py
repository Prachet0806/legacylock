"""Trigger service — sole owner of ACTIVE->GRACE->TRIGGERED transitions.

Both manual (router) and automatic (heartbeat_checker) paths delegate here so
the transition is atomic and idempotent: repeated triggers are a no-op success.

Transitions use optimistic compare-and-swap on VaultStatus.version
(UPDATE ... WHERE id AND version AND state), so concurrent schedulers/workers
cannot duplicate a transition.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from models import VaultStatus


def _get_or_create(db: Session, vault_id: int) -> VaultStatus:
    vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault_id).first()
    if not vs:
        vs = VaultStatus(vault_id=vault_id, state="active")
        db.add(vs)
        db.commit()
        db.refresh(vs)
    return vs


def trigger_vault(db: Session, vault_id: int, reason: str) -> tuple[VaultStatus, bool]:
    """CAS-transition vault to triggered. Returns (status, already_triggered)."""
    vs = _get_or_create(db, vault_id)
    if vs.state == "triggered":
        return vs, True
    now = datetime.now(UTC)
    ver = vs.version or 1
    updated = (
        db.query(VaultStatus)
        .filter(
            VaultStatus.id == vs.id,
            VaultStatus.version == ver,
            VaultStatus.state != "triggered",
        )
        .update(
            {
                "state": "triggered",
                "triggered_at": now,
                "trigger_reason": reason,
                "version": ver + 1,
                "updated_at": now,
            },
            synchronize_session="fetch",
        )
    )
    db.commit()
    db.refresh(vs)
    if updated == 0:
        return vs, True  # lost the race; another worker transitioned first
    return vs, False


def move_to_grace(db: Session, vault_id: int) -> tuple[VaultStatus, bool]:
    """CAS-transition vault active->grace. Returns (status, already_moved)."""
    vs = _get_or_create(db, vault_id)
    if vs.state != "active":
        return vs, True
    now = datetime.now(UTC)
    ver = vs.version or 1
    updated = (
        db.query(VaultStatus)
        .filter(
            VaultStatus.id == vs.id,
            VaultStatus.version == ver,
            VaultStatus.state == "active",
        )
        .update(
            {
                "state": "grace",
                "grace_started_at": now,
                "version": ver + 1,
                "updated_at": now,
            },
            synchronize_session="fetch",
        )
    )
    db.commit()
    db.refresh(vs)
    if updated == 0:
        return vs, True
    return vs, False

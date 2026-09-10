"""Vault trigger routes — manual and automatic trigger."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import get_settings
from deps import get_db, require_owner
from models import User, Vault, VaultStatus
from services.auth import verify_password
from services.audit import record_audit
from services.trigger_service import trigger_vault as _trigger_vault

router = APIRouter(
    prefix="/vault",
    tags=["vault-trigger"],
    dependencies=[Depends(require_owner)],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_vault(db: Session, current_user: User) -> Vault:
    """Get vault scoped to current user."""
    vault = db.query(Vault).filter(Vault.user_id == current_user.id).first()
    if not vault:
        raise HTTPException(status_code=404, detail="Vault not found")
    return vault


def _get_or_create_vault_status(db: Session, vault_id: int) -> VaultStatus:
    """Return the vault status row for a specific vault, creating it if absent."""
    vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault_id).first()
    if not vs:
        vs = VaultStatus(vault_id=vault_id, state="active")
        db.add(vs)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault_id).first()
            if not vs:
                raise
            return vs
        db.refresh(vs)
    return vs


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class VaultStatusOut(BaseModel):
    status: str
    grace_started_at: str | None
    triggered_at: str | None
    share_threshold: int | None = 0
    share_total: int | None = 0
    updated_at: str


class TriggerRequest(BaseModel):
    """Manual trigger requires re-authentication with password + explicit confirm."""
    password: str = Field(..., min_length=12, max_length=256, description="Owner's login password for re-authentication")
    confirm: Literal[True]


class ResetStatusRequest(BaseModel):
    """Reset status requires re-authentication with password + explicit confirm."""
    password: str = Field(..., min_length=12, max_length=256, description="Owner's login password for re-authentication")
    confirm: Literal[True]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/status", response_model=VaultStatusOut)
def get_status(current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    vault = _get_vault(db, current_user)
    vs = _get_or_create_vault_status(db, vault.id)
    return VaultStatusOut(
        status=vs.state,
        grace_started_at=vs.grace_started_at.isoformat() if vs.grace_started_at else None,
        triggered_at=vs.triggered_at.isoformat() if vs.triggered_at else None,
        share_threshold=vs.share_threshold,
        share_total=vs.share_total,
        updated_at=vs.updated_at.isoformat() if vs.updated_at else "",
    )


@router.post("/trigger")
def trigger_vault_route(data: TriggerRequest, current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    """Manually trigger the vault (requires re-authentication + confirm:true). Idempotent."""
    # Verify password for re-authentication
    if not verify_password(data.password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid password")

    vault = _get_vault(db, current_user)
    vs, already = _trigger_vault(db, vault.id, reason="manual")
    record_audit(db, vault.id, "owner", current_user.id, "vault.trigger",
                 {"reason": "manual", "already": already})

    return {"message": "Vault triggered — beneficiaries will receive access.",
            "triggered_at": vs.triggered_at.isoformat() if vs.triggered_at else "",
            "already": already}


@router.post("/reset-status")
def reset_status(data: ResetStatusRequest, current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    """Reset vault back to active (requires re-authentication + confirm:true). Dev/test only."""
    if get_settings().environment == "production":
        raise HTTPException(status_code=404, detail="Not found")
    # Verify password for re-authentication
    if not verify_password(data.password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid password")

    vault = _get_vault(db, current_user)
    vs = _get_or_create_vault_status(db, vault.id)
    now = datetime.now(UTC)
    vs.state = "active"
    vs.grace_started_at = None
    vs.triggered_at = None
    vs.trigger_reason = None
    vs.version = (vs.version or 1) + 1
    vs.updated_at = now
    db.commit()
    record_audit(db, vault.id, "owner", current_user.id, "vault.reset", {})
    return {"message": "Vault status reset to active."}

from datetime import UTC, datetime, timedelta
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models import AccessRequest, Beneficiary, Vault, VaultStatus
from deps import get_db, require_owner
from services.notifications import send_email

router = APIRouter(
    prefix="/vault",
    tags=["vault-trigger"],
    dependencies=[Depends(require_owner)],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_create_vault_status(db: Session) -> VaultStatus:
    """Return the singleton vault status row, creating it if absent."""
    vault = db.query(Vault).first()
    if not vault:
        raise HTTPException(status_code=404, detail="Vault not found")
    
    vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault.id).first()
    if not vs:
        vs = VaultStatus(vault_id=vault.id, state="active")
        db.add(vs)
        db.commit()
        db.refresh(vs)
    return vs


async def _auto_approve_access_requests(db: Session, vault_id: int) -> None:
    """Auto-approve all pending access requests when vault is triggered."""
    pending_requests = db.query(AccessRequest).filter(
        AccessRequest.vault_id == vault_id,
        AccessRequest.status == "pending"
    ).all()
    
    for req in pending_requests:
        req.status = "approved"
        req.approved_at = datetime.now(UTC)
        req.expires_at = datetime.now(UTC) + timedelta(days=30)
        
        # Notify beneficiary
        import asyncio
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


def _auto_approve_access_requests_sync(db: Session, vault_id: int) -> None:
    """Synchronous version of auto-approve for use in non-async contexts."""
    pending_requests = db.query(AccessRequest).filter(
        AccessRequest.vault_id == vault_id,
        AccessRequest.status == "pending"
    ).all()
    
    for req in pending_requests:
        req.status = "approved"
        req.approved_at = datetime.now(UTC)
        req.expires_at = datetime.now(UTC) + timedelta(days=30)
        
        # Note: In production, you'd want to send notifications asynchronously
        # For now, we skip email notifications in the sync version
    
    if pending_requests:
        db.commit()


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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/status", response_model=VaultStatusOut)
def get_status(db: Session = Depends(get_db)):
    vs = _get_or_create_vault_status(db)
    return VaultStatusOut(
        status=vs.state,
        grace_started_at=vs.grace_started_at.isoformat() if vs.grace_started_at else None,
        triggered_at=vs.triggered_at.isoformat() if vs.triggered_at else None,
        share_threshold=vs.share_threshold,
        share_total=vs.share_total,
        updated_at=vs.updated_at.isoformat() if vs.updated_at else "",
    )


@router.post("/trigger")
def trigger_vault(db: Session = Depends(get_db)):
    vs = _get_or_create_vault_status(db)
    if vs.state == "triggered":
        raise HTTPException(status_code=409, detail="Vault has already been triggered.")
    
    vault = db.query(Vault).first()
    if not vault:
        raise HTTPException(status_code=404, detail="Vault not found")
    
    vs.state = "triggered"
    vs.triggered_at = datetime.now(UTC)
    vs.updated_at = datetime.now(UTC)
    db.commit()
    
    # Auto-approve pending access requests (run synchronously for simplicity)
    _auto_approve_access_requests_sync(db, vault.id)
    
    return {"message": "Vault triggered — beneficiaries will receive access.", "triggered_at": vs.triggered_at.isoformat()}


@router.post("/reset-status")
def reset_status(db: Session = Depends(get_db)):
    """Reset vault back to active (for development/testing)."""
    vs = _get_or_create_vault_status(db)
    vs.state = "active"
    vs.grace_started_at = None
    vs.triggered_at = None
    vs.updated_at = datetime.now(UTC)
    db.commit()
    return {"message": "Vault status reset to active."}
"""Share management — client-side Shamir share storage/retrieval only.

Server does NOT generate, split, or reconstruct shares.
Shamir operations are performed exclusively in the browser (zero-knowledge).
"""

import base64

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from models import Beneficiary, User, Vault, VaultStatus
from deps import get_db, require_owner

router = APIRouter(
    prefix="/vault/shares",
    tags=["shares"],
    dependencies=[Depends(require_owner)],
)

# Public router — no API key required (for beneficiaries)
public_router = APIRouter(
    prefix="/vault/shares",
    tags=["shares"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_vault(db: Session, current_user: User | None = None) -> Vault:
    """Get vault scoped to owner. Fail closed (no cross-tenant fallback)."""
    if current_user is not None:
        vault = db.query(Vault).filter(Vault.user_id == current_user.id).first()
        if vault:
            return vault
        raise HTTPException(status_code=404, detail="Vault not found")
    raise HTTPException(status_code=404, detail="Vault not found")


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


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ShareConfig(BaseModel):
    """Client informs server of share configuration (threshold/total)."""
    threshold: int = Field(2, ge=2, le=255)
    total: int = Field(3, ge=2, le=255)


class ShareConfigOut(BaseModel):
    threshold: int
    total: int


class EncryptedShareAssign(BaseModel):
    """Client provides encrypted share for a beneficiary."""
    beneficiary_id: int
    encrypted_share_b64: str = Field(..., min_length=1)
    share_index: int = Field(..., ge=1, le=255)


class ShareStatusOut(BaseModel):
    beneficiary_id: int
    beneficiary_name: str
    share_index: int | None
    has_encrypted_share: bool
    has_public_key: bool
    invitation_status: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/config", response_model=ShareConfigOut)
def set_share_config(
    data: ShareConfig,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Client sets share threshold/total configuration on server."""
    if data.threshold > data.total:
        raise HTTPException(status_code=422, detail="threshold cannot exceed total")
    vault = _get_vault(db, current_user)
    vs = _get_vault_status(db, vault.id)
    vs.share_threshold = data.threshold
    vs.share_total = data.total
    db.commit()
    return ShareConfigOut(threshold=vs.share_threshold, total=vs.share_total)


@router.get("/config", response_model=ShareConfigOut)
def get_share_config(
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Get current share configuration."""
    vault = _get_vault(db, current_user)
    vs = _get_vault_status(db, vault.id)
    return ShareConfigOut(threshold=vs.share_threshold or 0, total=vs.share_total or 0)


@router.post("/encrypted-shares")
def assign_encrypted_share(
    data: EncryptedShareAssign,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Store an encrypted share for a beneficiary (client-generated)."""
    import base64 as _b64

    vault = _get_vault(db, current_user)
    try:
        raw = _b64.b64decode(data.encrypted_share_b64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="encrypted_share_b64 must be valid base64") from exc
    if len(raw) == 0 or len(raw) > 100_000:
        raise HTTPException(status_code=422, detail="encrypted_share_b64 size invalid")

    ben = db.query(Beneficiary).filter(
        Beneficiary.id == data.beneficiary_id,
        Beneficiary.vault_id == vault.id,
    ).first()
    if not ben:
        raise HTTPException(status_code=404, detail="Beneficiary not found")

    if ben.invitation_status != "accepted":
        raise HTTPException(status_code=400, detail="Beneficiary has not accepted invitation")

    ben.encrypted_share_data = data.encrypted_share_b64
    ben.share_index = data.share_index
    db.commit()

    return {"message": "Encrypted share assigned successfully"}


@router.get("", response_model=list[ShareStatusOut])
def list_shares(
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """List which beneficiaries have encrypted shares (without exposing share data)."""
    vault = _get_vault(db, current_user)
    beneficiaries = db.query(Beneficiary).filter(Beneficiary.vault_id == vault.id).all()
    return [
        ShareStatusOut(
            beneficiary_id=b.id,
            beneficiary_name=b.name,
            share_index=b.share_index or 0,
            has_encrypted_share=b.encrypted_share_data is not None,
            has_public_key=b.public_key is not None,
            invitation_status=b.invitation_status,
        )
        for b in beneficiaries
    ]


@public_router.get("/my-share")
def get_my_encrypted_share_legacy(db: Session = Depends(get_db)):
    """Legacy endpoint - beneficiary retrieves their encrypted share by invitation hash.
    
    DEPRECATED: Use /access/my-share with beneficiary auth instead.
    """
    # This is a legacy endpoint that doesn't require auth but uses invitation hash
    # In production, this should be removed or require the beneficiary to be authenticated
    raise HTTPException(status_code=410, detail="Use /access/my-share with beneficiary authentication")
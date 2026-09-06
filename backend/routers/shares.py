"""Share management — generate and distribute Shamir shares."""

import base64

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from models import Beneficiary, Vault, VaultStatus
from deps import get_db, require_owner
from services.shamir import reconstruct_secret, split_secret

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

def _get_vault(db: Session) -> Vault:
    """Get the vault (assuming single vault per owner)."""
    vault = db.query(Vault).first()
    if not vault:
        raise HTTPException(status_code=404, detail="Vault not found")
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


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    """Client sends the vault key (or wrapping key) to be split."""
    key_b64: str = Field(..., min_length=1, max_length=1_000_000,
                         description="Base64-encoded key to split")
    threshold: int = Field(2, ge=2, le=255)
    total: int = Field(3, ge=2, le=255)


class ShareOut(BaseModel):
    beneficiary_id: int
    beneficiary_name: str
    share_index: int
    has_share: bool


class ReconstructRequest(BaseModel):
    """Beneficiaries submit their shares to reconstruct the key."""
    shares_b64: list[str] = Field(..., min_length=2,
                                   description="List of base64-encoded shares")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/generate")
def generate_shares(data: GenerateRequest, db: Session = Depends(get_db)):
    """Split a key into shares and assign one per beneficiary."""
    beneficiaries = db.query(Beneficiary).all()

    if len(beneficiaries) < data.threshold:
        raise HTTPException(
            status_code=400,
            detail=f"Need at least {data.threshold} beneficiaries, but only {len(beneficiaries)} configured.",
        )

    # Adjust total to match beneficiary count if needed
    n = min(data.total, len(beneficiaries))
    k = min(data.threshold, n)

    secret = base64.b64decode(data.key_b64)
    shares = split_secret(secret, n, k)

    # Assign shares to beneficiaries
    for i, ben in enumerate(beneficiaries[:n]):
        ben.share_data = base64.b64encode(shares[i]).decode()
        ben.share_index = i + 1

    # Update vault status with threshold config
    vs = _get_vault_status(db)
    vs.share_threshold = k
    vs.share_total = n
    db.commit()

    return {
        "message": f"Generated {n} shares with threshold {k}.",
        "shares_assigned": n,
        "threshold": k,
    }


@router.get("", response_model=list[ShareOut])
def list_shares(db: Session = Depends(get_db)):
    """List which beneficiaries have shares (without exposing share data)."""
    beneficiaries = db.query(Beneficiary).all()
    return [
        ShareOut(
            beneficiary_id=b.id,
            beneficiary_name=b.name,
            share_index=b.share_index or 0,
            has_share=b.share_data is not None,
        )
        for b in beneficiaries
    ]


@public_router.post("/reconstruct")
def reconstruct_key(data: ReconstructRequest):
    """Reconstruct the original key from submitted shares.

    This endpoint does NOT require API key auth — beneficiaries use it.
    """
    try:
        decoded_shares = [base64.b64decode(s) for s in data.shares_b64]
        secret = reconstruct_secret(decoded_shares)
        return {"key_b64": base64.b64encode(secret).decode()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Reconstruction failed: {str(e)}")
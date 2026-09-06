"""Beneficiary access routes — Phase 2 implementation."""

import secrets
import base64
import os
from datetime import UTC, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from models import AccessRequest, Beneficiary, User, Vault, VaultStatus
from deps import get_db, get_current_beneficiary, require_beneficiary, require_owner
from services.auth import create_access_token
from services.notifications import send_email
from services.shamir import split_secret, reconstruct_secret

# Public router — no auth required (for invitation acceptance)
public_router = APIRouter(
    prefix="/access",
    tags=["access"],
)

# Protected router — requires beneficiary auth
router = APIRouter(
    prefix="/access",
    tags=["access"],
    dependencies=[Depends(require_beneficiary)],
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


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class InvitationAccept(BaseModel):
    """Beneficiary accepts invitation."""
    pass


class InvitationAcceptOut(BaseModel):
    message: str
    beneficiary_id: int
    access_token: str
    token_type: str = "bearer"


class AccessRequestCreate(BaseModel):
    """Beneficiary requests access to vault."""
    reason: str | None = Field(None, max_length=1000)


class AccessRequestOut(BaseModel):
    id: int
    status: str
    reason: str | None
    created_at: str
    approved_at: str | None
    expires_at: str | None
    model_config = {"from_attributes": True}


class AccessRequestListOut(BaseModel):
    id: int
    beneficiary_name: str
    beneficiary_email: str
    status: str
    reason: str | None
    created_at: str
    approved_at: str | None


class AccessRequestApprove(BaseModel):
    """Owner approves/denies access request."""
    approve: bool


class AccessStatusOut(BaseModel):
    """Vault status for beneficiary."""
    vault_status: str
    vault_name: str
    share_index: int | None
    share_total: int
    share_threshold: int
    has_share: bool


class ShareSubmit(BaseModel):
    """Beneficiary submits their Shamir share."""
    share_b64: str = Field(..., min_length=1)


class ShareSubmitOut(BaseModel):
    message: str
    key_b64: str | None = None


# ---------------------------------------------------------------------------
# Public Routes (no auth required)
# ---------------------------------------------------------------------------

@public_router.post("/invite/{invitation_hash}/accept", response_model=InvitationAcceptOut)
def accept_invitation(invitation_hash: str, db: Session = Depends(get_db)):
    """Beneficiary accepts invitation via email link."""
    beneficiary = db.query(Beneficiary).filter(
        Beneficiary.invitation_hash == invitation_hash
    ).first()
    
    if not beneficiary:
        raise HTTPException(status_code=404, detail="Invalid or expired invitation")
    
    if beneficiary.invitation_status == "accepted":
        raise HTTPException(status_code=409, detail="Invitation already accepted")
    
    if beneficiary.invitation_status == "expired":
        raise HTTPException(status_code=410, detail="Invitation has expired")
    
    # Check if invitation is older than 7 days
    if beneficiary.invitation_sent_at:
        expiry = beneficiary.invitation_sent_at + timedelta(days=7)
        if datetime.now(UTC) > expiry:
            beneficiary.invitation_status = "expired"
            db.commit()
            raise HTTPException(status_code=410, detail="Invitation has expired")
    
    # Mark invitation as accepted
    beneficiary.invitation_status = "accepted"
    beneficiary.invitation_accepted_at = datetime.now(UTC)
    db.commit()
    
    # Create access token for beneficiary
    vault = _get_vault(db)
    access_token = create_access_token(beneficiary.id, vault.id)
    
    return InvitationAcceptOut(
        message="Invitation accepted. You can now access the vault.",
        beneficiary_id=beneficiary.id,
        access_token=access_token,
    )


@public_router.get("/invite/{invitation_hash}/status")
def check_invitation_status(invitation_hash: str, db: Session = Depends(get_db)):
    """Check invitation status without accepting."""
    beneficiary = db.query(Beneficiary).filter(
        Beneficiary.invitation_hash == invitation_hash
    ).first()
    
    if not beneficiary:
        raise HTTPException(status_code=404, detail="Invalid invitation")
    
    # Check expiry
    if beneficiary.invitation_sent_at:
        expiry = beneficiary.invitation_sent_at + timedelta(days=7)
        is_expired = datetime.now(UTC) > expiry
    else:
        is_expired = False
    
    return {
        "beneficiary_name": beneficiary.name,
        "beneficiary_email": beneficiary.email,
        "invitation_status": beneficiary.invitation_status,
        "is_expired": is_expired,
        "invitation_sent_at": beneficiary.invitation_sent_at.isoformat() if beneficiary.invitation_sent_at else None,
    }


# ---------------------------------------------------------------------------
# Protected Routes (beneficiary auth required)
# ---------------------------------------------------------------------------

@router.post("/request", response_model=AccessRequestOut, status_code=status.HTTP_201_CREATED)
def create_access_request(
    data: AccessRequestCreate,
    current_beneficiary: Beneficiary = Depends(require_beneficiary),
    db: Session = Depends(get_db),
):
    """Beneficiary requests access to the vault."""
    # Check if there's already a pending request
    existing = db.query(AccessRequest).filter(
        AccessRequest.beneficiary_id == current_beneficiary.id,
        AccessRequest.status == "pending"
    ).first()
    
    if existing:
        raise HTTPException(status_code=409, detail="You already have a pending access request")
    
    # Check vault status
    vault = _get_vault(db)
    vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault.id).first()
    vault_status = vs.state if vs else "active"
    
    # If vault is triggered, auto-approve
    status_value = "approved" if vault_status == "triggered" else "pending"
    approved_at = datetime.now(UTC) if status_value == "approved" else None
    expires_at = datetime.now(UTC) + timedelta(days=30) if status_value == "approved" else None
    
    request = AccessRequest(
        vault_id=vault.id,
        beneficiary_id=current_beneficiary.id,
        status=status_value,
        request_reason=data.reason,
        approved_at=approved_at,
        expires_at=expires_at,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    
    # If auto-approved due to trigger, notify beneficiary
    if status_value == "approved":
        import asyncio
        asyncio.get_event_loop().create_task(
            send_email(
                current_beneficiary.email,
                "LegacyLock — Access Granted",
                f"Your access request has been approved. You can now access the vault.",
            )
        )
    
    return AccessRequestOut(
        id=request.id,
        status=request.status,
        reason=request.request_reason,
        created_at=request.created_at.isoformat() if request.created_at else "",
        approved_at=request.approved_at.isoformat() if request.approved_at else None,
        expires_at=request.expires_at.isoformat() if request.expires_at else None,
    )


@router.get("/requests", response_model=list[AccessRequestOut])
def list_my_access_requests(
    current_beneficiary: Beneficiary = Depends(require_beneficiary),
    db: Session = Depends(get_db),
):
    """List all access requests for the current beneficiary."""
    requests = db.query(AccessRequest).filter(
        AccessRequest.beneficiary_id == current_beneficiary.id
    ).order_by(AccessRequest.created_at.desc()).all()
    
    return [
        AccessRequestOut(
            id=r.id,
            status=r.status,
            reason=r.request_reason,
            created_at=r.created_at.isoformat() if r.created_at else "",
            approved_at=r.approved_at.isoformat() if r.approved_at else None,
            expires_at=r.expires_at.isoformat() if r.expires_at else None,
        )
        for r in requests
    ]


@router.get("/status", response_model=AccessStatusOut)
def get_access_status(
    current_beneficiary: Beneficiary = Depends(require_beneficiary),
    db: Session = Depends(get_db),
):
    """Get vault status and beneficiary's share info."""
    vault = _get_vault(db)
    vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault.id).first()
    
    has_share = current_beneficiary.share_data is not None
    
    return AccessStatusOut(
        vault_status=vs.state if vs else "active",
        vault_name=vault.name,
        share_index=current_beneficiary.share_index,
        share_total=vs.share_total if vs else 0,
        share_threshold=vs.share_threshold if vs else 0,
        has_share=has_share,
    )


@router.post("/share", response_model=ShareSubmitOut)
def submit_share(
    data: ShareSubmit,
    current_beneficiary: Beneficiary = Depends(require_beneficiary),
    db: Session = Depends(get_db),
):
    """Beneficiary submits their Shamir share for recovery."""
    vault = _get_vault(db)
    vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault.id).first()
    
    if not vs or vs.state != "triggered":
        raise HTTPException(status_code=403, detail="Vault is not triggered. Shares can only be submitted after vault release.")
    
    if not current_beneficiary.share_data:
        raise HTTPException(status_code=403, detail="You have not been assigned a share")
    
    # Verify the submitted share matches the beneficiary's assigned share
    if data.share_b64 != current_beneficiary.share_data:
        raise HTTPException(status_code=400, detail="Invalid share. Does not match your assigned share.")
    
    # If we have enough shares, reconstruct the key
    # For now, just return the key - in production, this would trigger reconstruction
    # when enough shares are submitted
    
    # Get all approved access requests with shares
    approved_requests = db.query(AccessRequest).filter(
        AccessRequest.vault_id == vault.id,
        AccessRequest.status == "approved"
    ).all()
    
    # Collect shares from approved beneficiaries
    shares = []
    for req in approved_requests:
        ben = req.beneficiary
        if ben.share_data:
            shares.append(ben.share_data)
    
    if len(shares) >= (vs.share_threshold if vs else 2):
        # Reconstruct key
        import base64
        from services.shamir import reconstruct_secret
        
        try:
            decoded_shares = [base64.b64decode(s) for s in shares]
            secret = reconstruct_secret(decoded_shares)
            key_b64 = base64.b64encode(secret).decode()
            
            return ShareSubmitOut(
                message=f"Share submitted. Key reconstructed from {len(shares)} shares.",
                key_b64=key_b64,
            )
        except Exception as e:
            return ShareSubmitOut(
                message=f"Share submitted, but reconstruction failed: {str(e)}",
            )
    
    return ShareSubmitOut(
        message=f"Share submitted. Waiting for {vs.share_threshold - len(shares)} more shares to reconstruct key.",
    )


# ---------------------------------------------------------------------------
# Owner Routes (require owner auth)
# ---------------------------------------------------------------------------

owner_router = APIRouter(
    prefix="/access",
    tags=["access"],
    dependencies=[Depends(require_owner)],
)


@owner_router.get("/requests", response_model=list[AccessRequestListOut])
def list_access_requests(
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List all access requests for the vault (owner view)."""
    vault = _get_vault(db)
    
    query = db.query(AccessRequest).filter(AccessRequest.vault_id == vault.id)
    
    if status_filter:
        query = query.filter(AccessRequest.status == status_filter)
    
    requests = query.order_by(AccessRequest.created_at.desc()).all()
    
    return [
        AccessRequestListOut(
            id=r.id,
            beneficiary_name=r.beneficiary.name,
            beneficiary_email=r.beneficiary.email,
            status=r.status,
            reason=r.request_reason,
            created_at=r.created_at.isoformat() if r.created_at else "",
            approved_at=r.approved_at.isoformat() if r.approved_at else None,
        )
        for r in requests
    ]


@owner_router.post("/requests/{request_id}/approve")
def approve_access_request(
    request_id: int,
    data: AccessRequestApprove,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Approve or deny an access request."""
    vault = _get_vault(db)
    
    request = db.query(AccessRequest).filter(
        AccessRequest.id == request_id,
        AccessRequest.vault_id == vault.id
    ).first()
    
    if not request:
        raise HTTPException(status_code=404, detail="Access request not found")
    
    if request.status != "pending":
        raise HTTPException(status_code=409, detail=f"Request already {request.status}")
    
    if data.approve:
        request.status = "approved"
        request.approved_at = datetime.now(UTC)
        request.approved_by = current_user.id
        request.expires_at = datetime.now(UTC) + timedelta(days=30)
        message = "Access request approved"
    else:
        request.status = "denied"
        request.approved_at = datetime.now(UTC)
        request.approved_by = current_user.id
        message = "Access request denied"
    
    db.commit()
    
    # Notify beneficiary
    import asyncio
    asyncio.get_event_loop().create_task(
        send_email(
            request.beneficiary.email,
            f"LegacyLock — Access Request {request.status.capitalize()}",
            f"Your access request has been {request.status}.",
        )
    )
    
    return {"message": message, "status": request.status}


@owner_router.post("/generate-shares")
def generate_shares_for_all(
    threshold: int = 2,
    db: Session = Depends(get_db),
):
    """Generate Shamir shares for all beneficiaries who accepted invitations."""
    vault = _get_vault(db)
    
    # Get beneficiaries who accepted invitations
    beneficiaries = db.query(Beneficiary).filter(
        Beneficiary.vault_id == vault.id,
        Beneficiary.invitation_status == "accepted"
    ).all()
    
    if len(beneficiaries) < threshold:
        raise HTTPException(
            status_code=400,
            detail=f"Need at least {threshold} beneficiaries with accepted invitations, but only {len(beneficiaries)} found."
        )
    
    # Generate a master key to split
    import base64
    import os
    master_key = os.urandom(32)  # 256-bit key
    shares = split_secret(master_key, len(beneficiaries), threshold)
    
    # Assign shares to beneficiaries
    for i, ben in enumerate(beneficiaries):
        ben.share_data = base64.b64encode(shares[i]).decode()
        ben.share_index = i + 1
    
    # Update vault status
    vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault.id).first()
    if not vs:
        vs = VaultStatus(vault_id=vault.id)
        db.add(vs)
    vs.share_threshold = threshold
    vs.share_total = len(beneficiaries)
    vs.updated_at = datetime.now(UTC)
    
    db.commit()
    
    return {
        "message": f"Generated {len(beneficiaries)} shares with threshold {threshold}.",
        "shares_assigned": len(beneficiaries),
        "threshold": threshold,
        "key_b64": base64.b64encode(master_key).decode(),  # Only returned once!
    }


@owner_router.get("/shares")
def list_shares(
    db: Session = Depends(get_db),
):
    """List which beneficiaries have shares (owner view)."""
    vault = _get_vault(db)
    
    beneficiaries = db.query(Beneficiary).filter(Beneficiary.vault_id == vault.id).all()
    
    return [
        {
            "beneficiary_id": b.id,
            "beneficiary_name": b.name,
            "beneficiary_email": b.email,
            "share_index": b.share_index,
            "has_share": b.share_data is not None,
            "invitation_status": b.invitation_status,
        }
        for b in beneficiaries
    ]
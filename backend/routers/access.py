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
from config import get_settings

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

def _get_vault(db: Session, current_user: User | Beneficiary | None = None) -> Vault:
    """Get vault scoped to user/beneficiary. Fail closed (no cross-tenant fallback)."""
    vault_id = None
    if current_user is not None:
        vault_id = getattr(current_user, "vault_id", None)
        if vault_id is None and isinstance(current_user, User):
            vault = db.query(Vault).filter(Vault.user_id == current_user.id).first()
            if vault:
                return vault
            raise HTTPException(status_code=404, detail="Vault not found")
        if vault_id is not None:
            vault = db.query(Vault).filter(Vault.id == vault_id).first()
            if vault:
                return vault
            raise HTTPException(status_code=404, detail="Vault not found")
    raise HTTPException(status_code=404, detail="Vault not found")


def _queue_email(to: str, subject: str, body: str) -> None:
    """Best-effort in-process email dispatch (no fire-and-forget crash)."""
    try:
        import asyncio

        from services.notifications import send_email

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            loop.create_task(send_email(to, subject, body))
        else:
            # No running loop (tests/CLI): run inline, swallow errors
            try:
                asyncio.run(send_email(to, subject, body))
            except RuntimeError:
                pass
    except Exception:
        pass


def _require_share_access(current_beneficiary: Beneficiary, db: Session) -> Vault:
    """Gate share retrieval: require approval or triggered vault."""
    vault = _get_vault(db, current_beneficiary)
    vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault.id).first()
    state = vs.state if vs else "active"
    if state == "triggered":
        return vault
    req = (
        db.query(AccessRequest)
        .filter(
            AccessRequest.beneficiary_id == current_beneficiary.id,
            AccessRequest.vault_id == vault.id,
            AccessRequest.status == "approved",
        )
        .first()
    )
    if req is None:
        raise HTTPException(status_code=403, detail="Access not approved")
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
    has_encrypted_share: bool


class PublicKeySubmit(BaseModel):
    """Beneficiary submits their public key for share encryption."""
    public_key_b64: str = Field(..., min_length=1, description="Base64-encoded public key")


class PublicKeySubmitOut(BaseModel):
    message: str


class EncryptedShareStore(BaseModel):
    """Owner stores an encrypted share for a beneficiary."""
    beneficiary_id: int
    encrypted_share_b64: str = Field(..., min_length=1, description="Base64-encrypted share")
    share_index: int = Field(..., ge=1, le=255)


class EncryptedShareStoreOut(BaseModel):
    message: str


class EncryptedShareRetrieveOut(BaseModel):
    """Beneficiary retrieves their encrypted share."""
    beneficiary_id: int
    encrypted_share_b64: str | None
    share_index: int | None


# ---------------------------------------------------------------------------
# Public Routes (no auth required)
# ---------------------------------------------------------------------------

@public_router.post("/invite/{invitation_hash}/accept", response_model=InvitationAcceptOut)
def accept_invitation(invitation_hash: str, response: Response, db: Session = Depends(get_db)):
    """Beneficiary accepts invitation via email link (one-time, rotates hash)."""
    beneficiary = db.query(Beneficiary).filter(
        Beneficiary.invitation_hash == invitation_hash
    ).first()

    if not beneficiary:
        # Generic to avoid enumeration oracle
        raise HTTPException(status_code=404, detail="Invalid or expired invitation")

    if beneficiary.invitation_status == "accepted":
        raise HTTPException(status_code=409, detail="Invitation already accepted")

    if beneficiary.invitation_status == "expired":
        raise HTTPException(status_code=410, detail="Invitation has expired")

    # Check if invitation is older than 7 days
    if beneficiary.invitation_sent_at:
        expiry = beneficiary.invitation_sent_at + timedelta(days=7)
        now = datetime.now(UTC)
        sent = beneficiary.invitation_sent_at
        if sent.tzinfo is None:
            sent = sent.replace(tzinfo=UTC)
            expiry = sent + timedelta(days=7)
        if now > expiry:
            beneficiary.invitation_status = "expired"
            db.commit()
            raise HTTPException(status_code=410, detail="Invitation has expired")

    # Mark invitation as accepted and rotate hash so link cannot be replayed
    beneficiary.invitation_status = "accepted"
    beneficiary.invitation_accepted_at = datetime.now(UTC)
    beneficiary.invitation_hash = secrets.token_urlsafe(32)
    db.commit()

    # Create beneficiary-scoped access token (explicit role)
    vault = _get_vault(db, beneficiary)
    access_token = create_access_token(beneficiary.id, vault.id, role="beneficiary")

    # Also set beneficiary HttpOnly cookie for browser flows
    try:
        secure = get_settings().environment == "production"
    except Exception:
        secure = False
    response.set_cookie(
        key="legacylock_beneficiary_session",
        value=access_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=15 * 60,
        path="/",
    )

    return InvitationAcceptOut(
        message="Invitation accepted. You can now access the vault.",
        beneficiary_id=beneficiary.id,
        access_token=access_token,
    )


@public_router.get("/invite/{invitation_hash}/status")
def check_invitation_status(invitation_hash: str, db: Session = Depends(get_db)):
    """Check invitation status without accepting (minimal disclosure)."""
    beneficiary = db.query(Beneficiary).filter(
        Beneficiary.invitation_hash == invitation_hash
    ).first()

    if not beneficiary:
        raise HTTPException(status_code=404, detail="Invalid invitation")

    # Check expiry
    if beneficiary.invitation_sent_at:
        sent = beneficiary.invitation_sent_at
        if sent.tzinfo is None:
            from datetime import timezone

            sent = sent.replace(tzinfo=timezone.utc)
        expiry = sent + timedelta(days=7)
        is_expired = datetime.now(UTC) > expiry
    else:
        is_expired = False

    # Minimal: do not leak email unless link is valid; still avoid name enumeration
    # by requiring full hash (256-bit) — return only status flags.
    return {
        "invitation_status": beneficiary.invitation_status,
        "is_expired": is_expired,
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
    vault = _get_vault(db, current_beneficiary)
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
    
    # If auto-approved due to trigger, notify beneficiary (best-effort)
    if status_value == "approved":
        _queue_email(
            current_beneficiary.email,
            "LegacyLock — Access Granted",
            "Your access request has been approved. You can now access the vault.",
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
    """Get vault status and beneficiary's encrypted share info (gated)."""
    vault = _require_share_access(current_beneficiary, db)
    vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault.id).first()

    has_encrypted_share = current_beneficiary.encrypted_share_data is not None

    return AccessStatusOut(
        vault_status=vs.state if vs else "active",
        vault_name=vault.name,
        share_index=current_beneficiary.share_index,
        has_encrypted_share=has_encrypted_share,
    )


@router.post("/public-key", response_model=PublicKeySubmitOut)
def submit_public_key(
    data: PublicKeySubmit,
    current_beneficiary: Beneficiary = Depends(require_beneficiary),
    db: Session = Depends(get_db),
):
    """Beneficiary submits their public key for share encryption."""
    import base64 as _b64

    try:
        raw = _b64.b64decode(data.public_key_b64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="public_key_b64 must be valid base64") from exc
    if len(raw) == 0 or len(raw) > 10_000:
        raise HTTPException(status_code=422, detail="public_key_b64 size invalid")
    current_beneficiary.public_key = data.public_key_b64
    db.commit()
    return PublicKeySubmitOut(message="Public key stored successfully")


@router.get("/my-share", response_model=EncryptedShareRetrieveOut)
def get_my_encrypted_share(
    current_beneficiary: Beneficiary = Depends(require_beneficiary),
    db: Session = Depends(get_db),
):
    """Beneficiary retrieves their encrypted share (requires approval/trigger)."""
    _require_share_access(current_beneficiary, db)
    return EncryptedShareRetrieveOut(
        beneficiary_id=current_beneficiary.id,
        encrypted_share_b64=current_beneficiary.encrypted_share_data,
        share_index=current_beneficiary.share_index,
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
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """List all access requests for the vault (owner view)."""
    vault = _get_vault(db, current_user)
    
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
    vault = _get_vault(db, current_user)
    
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

    # Notify beneficiary (best-effort, in-process)
    _queue_email(
        request.beneficiary.email,
        f"LegacyLock — Access Request {request.status.capitalize()}",
        f"Your access request has been {request.status}.",
    )

    return {"message": message, "status": request.status}


@owner_router.post("/encrypted-shares", response_model=EncryptedShareStoreOut)
def store_encrypted_share(
    data: EncryptedShareStore,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Owner stores an encrypted share for a beneficiary (client-generated)."""
    import base64 as _b64

    vault = _get_vault(db, current_user)

    try:
        raw = _b64.b64decode(data.encrypted_share_b64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="encrypted_share_b64 must be valid base64") from exc
    if len(raw) == 0 or len(raw) > 100_000:
        raise HTTPException(status_code=422, detail="encrypted_share_b64 size invalid")

    beneficiary = db.query(Beneficiary).filter(
        Beneficiary.id == data.beneficiary_id,
        Beneficiary.vault_id == vault.id
    ).first()
    
    if not beneficiary:
        raise HTTPException(status_code=404, detail="Beneficiary not found")
    
    if beneficiary.invitation_status != "accepted":
        raise HTTPException(status_code=400, detail="Beneficiary has not accepted invitation")
    
    beneficiary.encrypted_share_data = data.encrypted_share_b64
    beneficiary.share_index = data.share_index
    db.commit()
    
    return EncryptedShareStoreOut(message="Encrypted share stored successfully")


@owner_router.get("/encrypted-shares")
def list_encrypted_shares(
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """List which beneficiaries have encrypted shares (owner view)."""
    vault = _get_vault(db, current_user)
    
    beneficiaries = db.query(Beneficiary).filter(Beneficiary.vault_id == vault.id).all()
    
    return [
        {
            "beneficiary_id": b.id,
            "beneficiary_name": b.name,
            "beneficiary_email": b.email,
            "share_index": b.share_index,
            "has_encrypted_share": b.encrypted_share_data is not None,
            "has_public_key": b.public_key is not None,
            "invitation_status": b.invitation_status,
        }
        for b in beneficiaries
    ]
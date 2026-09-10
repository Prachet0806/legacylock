"""Beneficiary access routes — new architecture.

This module handles:
- Invitation acceptance (public)
- Beneficiary session creation (creates short-lived session after invitation)
- Beneficiary status check (gated by vault trigger)
- Owner share assignment metadata
"""

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import get_settings
from deps import get_current_beneficiary, get_db, require_beneficiary, require_owner
from models import Beneficiary, User, Vault, VaultStatus
from services.auth import create_access_token, hash_token

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


def _find_by_invite(db: Session, raw_token: str) -> Beneficiary | None:
    """Look up beneficiary by invitation token. DB stores SHA-256 hash only.

    Falls back to raw match for legacy rows created before hashing.
    """
    hashed = hash_token(raw_token)
    b = db.query(Beneficiary).filter(Beneficiary.invitation_hash == hashed).first()
    if b:
        return b
    return db.query(Beneficiary).filter(Beneficiary.invitation_hash == raw_token).first()


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


class AccessStatusOut(BaseModel):
    """Vault status for beneficiary."""
    vault_status: str
    vault_name: str
    share_index: int | None
    # No has_encrypted_share - backend doesn't store shares


class SessionCreateOut(BaseModel):
    """Response for beneficiary session creation."""
    message: str
    beneficiary_id: int
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 1800  # 30 minutes


class ShareAssignmentOut(BaseModel):
    """Owner view of beneficiary share assignment."""
    beneficiary_id: int
    beneficiary_name: str
    beneficiary_email: str
    share_index: int | None
    invitation_status: str
    has_public_key: bool = False  # Deprecated - kept for compatibility


class ShareSubmit(BaseModel):
    share: str | None = None
    share_hash: str | None = None


# ---------------------------------------------------------------------------
# Public Routes (no auth required)
# ---------------------------------------------------------------------------

@public_router.post("/invite/{invitation_hash}/accept", response_model=InvitationAcceptOut)
def accept_invitation(invitation_hash: str, response: Response, db: Session = Depends(get_db)):
    """Beneficiary accepts invitation via email link (one-time, rotates hash)."""
    beneficiary = _find_by_invite(db, invitation_hash)

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
    beneficiary.invitation_hash = hash_token(secrets.token_urlsafe(32))
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
    beneficiary = _find_by_invite(db, invitation_hash)

    if not beneficiary:
        raise HTTPException(status_code=404, detail="Invalid invitation")

    # Check expiry
    if beneficiary.invitation_sent_at:
        sent = beneficiary.invitation_sent_at
        if sent.tzinfo is None:

            sent = sent.replace(tzinfo=UTC)
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


@public_router.post("/session", response_model=SessionCreateOut)
def create_beneficiary_session(
    response: Response,
    current_beneficiary: Beneficiary = Depends(get_current_beneficiary),
    db: Session = Depends(get_db),
):
    """Create a new beneficiary session (refresh token flow for beneficiaries).
    
    This endpoint allows beneficiaries to refresh their session using their
    existing valid beneficiary token. The new token has a 30-minute lifetime.
    """
    # Verify beneficiary has accepted invitation
    if current_beneficiary.invitation_status != "accepted":
        raise HTTPException(status_code=403, detail="Invitation not accepted")

    vault = _get_vault(db, current_beneficiary)
    access_token = create_access_token(current_beneficiary.id, vault.id, role="beneficiary")

    # Set beneficiary HttpOnly cookie
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
        max_age=30 * 60,  # 30 minutes
        path="/",
    )

    return SessionCreateOut(
        message="Session created",
        beneficiary_id=current_beneficiary.id,
        access_token=access_token,
    )


# ---------------------------------------------------------------------------
# Protected Routes (beneficiary auth required)
# ---------------------------------------------------------------------------

@router.get("/status", response_model=AccessStatusOut)
def get_access_status(
    current_beneficiary: Beneficiary = Depends(require_beneficiary),
    db: Session = Depends(get_db),
):
    """Get vault status and beneficiary's share index (gated by trigger)."""
    vault = _get_vault(db, current_beneficiary)
    vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault.id).first()
    vault_state = vs.state if vs else "active"

    # Gate: only allow status access if vault is triggered
    if vault_state != "triggered":
        raise HTTPException(status_code=403, detail="Vault not triggered")

    return AccessStatusOut(
        vault_status=vault_state,
        vault_name=vault.name,
        share_index=current_beneficiary.share_index,
    )


@router.post("/share")
def submit_share(
    data: ShareSubmit,
    current_beneficiary: Beneficiary = Depends(require_beneficiary),
    db: Session = Depends(get_db),
):
    """Submit a Shamir share hash for recovery.

    Backend stores only the SHA-256 hash (idempotent resubmit = no-op) and
    never reconstructs the VMK. Vault must be TRIGGERED.
    """
    from services.share_service import submit_share as _submit

    vault = _get_vault(db, current_beneficiary)
    vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault.id).first()
    if not vs or vs.state != "triggered":
        raise HTTPException(status_code=403, detail="Vault not triggered")
    raw = data.share if data.share is not None else data.share_hash
    if not raw:
        raise HTTPException(status_code=400, detail="share is required")
    return _submit(db, vault.id, current_beneficiary.id, raw)


# ---------------------------------------------------------------------------
# Owner Routes (require owner auth)
# ---------------------------------------------------------------------------

owner_router = APIRouter(
    prefix="/access",
    tags=["access"],
    dependencies=[Depends(require_owner)],
)


@owner_router.get("/share-assignments", response_model=list[ShareAssignmentOut])
def list_share_assignments(
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """List which beneficiaries have share assignments (owner view).
    
    Returns metadata only - no encrypted shares or public keys.
    """
    vault = _get_vault(db, current_user)
    beneficiaries = db.query(Beneficiary).filter(Beneficiary.vault_id == vault.id).all()

    return [
        ShareAssignmentOut(
            beneficiary_id=b.id,
            beneficiary_name=b.name,
            beneficiary_email=b.email,
            share_index=b.share_index,
            invitation_status=b.invitation_status,
            has_public_key=False,  # Deprecated
        )
        for b in beneficiaries
    ]

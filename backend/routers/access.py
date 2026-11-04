"""Beneficiary access routes — new architecture.

This module handles:
- Invitation acceptance (public)
- Beneficiary session creation (creates short-lived session after invitation)
- Beneficiary status check (gated by vault trigger)
- Owner share assignment metadata
"""

import json
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config import get_settings
from deps import get_db, require_beneficiary, require_owner
from models import Beneficiary, User, Vault, VaultMessage, VaultStatus
from services.audit import record_audit
from services.auth import (
    hash_token,
)

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
            vault = (
                db.query(Vault)
                .filter(Vault.user_id == current_user.id, Vault.is_primary.is_(True))
                .first()
            )
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
    """Look up beneficiary by invitation token. The DB stores SHA-256 hashes
    only — pre-hashing rows cannot exist and are treated as invalid."""
    return (
        db.query(Beneficiary).filter(Beneficiary.invitation_hash == hash_token(raw_token)).first()
    )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class InvitationAccept(BaseModel):
    """Beneficiary accepts invitation."""

    pass


class InvitationCredential(BaseModel):
    token: str = Field(..., min_length=20, max_length=256)


@public_router.post("/invitation/accept")
def accept_fragment_invitation(
    data: InvitationCredential, response: Response, db: Session = Depends(get_db)
):
    return accept_invitation(data.token, response, db)


class InvitationAcceptOut(BaseModel):
    # Tokens travel via HttpOnly cookies only — never in JSON bodies.
    message: str
    beneficiary_id: int


class AccessStatusOut(BaseModel):
    """Vault status for beneficiary."""

    vault_status: str
    vault_name: str
    share_index: int | None
    recovery_threshold: int = 2
    recovery_total: int = 3
    recovery_generation: str | None = None
    beneficiary_id: int
    material_revision: int
    # No has_encrypted_share - backend doesn't store shares


class SessionCreateOut(BaseModel):
    # Tokens travel via HttpOnly cookies only — never in JSON bodies.
    message: str
    beneficiary_id: int
    expires_in: int = 1800  # 30 minutes


class ShareAssignmentOut(BaseModel):
    """Owner view of beneficiary share assignment."""

    beneficiary_id: int
    beneficiary_name: str
    beneficiary_email: str
    share_index: int | None
    invitation_status: str
    has_public_key: bool = False  # Deprecated - kept for compatibility


# ---------------------------------------------------------------------------
# Public Routes (no auth required)
# ---------------------------------------------------------------------------


def accept_invitation(invitation_hash: str, response: Response, db: Session = Depends(get_db)):
    """Beneficiary accepts invitation via email link (one-time, rotates hash)."""
    beneficiary = _find_by_invite(db, invitation_hash)

    if not beneficiary:
        # Generic to avoid enumeration oracle
        raise HTTPException(status_code=404, detail="Invalid or expired invitation")

    # All recipient mutations use vault -> recipient -> credential lock order.
    from services.trigger_service import lock_status

    lock_status(db, beneficiary.vault_id)
    beneficiary = (
        db.query(Beneficiary)
        .filter_by(id=beneficiary.id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    if beneficiary.invitation_hash != hash_token(invitation_hash):
        raise HTTPException(404, "Invalid or expired invitation")

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
            record_audit(
                db, beneficiary.vault_id, "beneficiary", beneficiary.id, "invitation.expired", {}
            )
            db.commit()
            raise HTTPException(status_code=410, detail="Invitation has expired")

    # Atomic single-use transition: concurrent accepts must not both succeed.
    # The conditional UPDATE only flips pending->accepted; rowcount 0 means
    # another request won the race (or status changed) — re-read for the
    # correct error.
    from models import Beneficiary as _Ben

    now = datetime.now(UTC)
    flipped = (
        db.query(_Ben)
        .filter(
            _Ben.id == beneficiary.id,
            _Ben.invitation_status == "sent",
            _Ben.invitation_hash == hash_token(invitation_hash),
            _Ben.contact_revision == beneficiary.contact_revision,
        )
        .update(
            {
                _Ben.invitation_status: "accepted",
                _Ben.invitation_accepted_at: now,
                _Ben.invitation_hash: hash_token(secrets.token_urlsafe(32)),
            },
            synchronize_session=False,
        )
    )
    db.flush()
    if not flipped:
        db.refresh(beneficiary)
        if beneficiary.invitation_status == "accepted":
            raise HTTPException(status_code=409, detail="Invitation already accepted")
        raise HTTPException(status_code=404, detail="Invalid or expired invitation")
    db.refresh(beneficiary)

    from services.sessions import issue

    vault = _get_vault(db, beneficiary)
    access_token, raw_refresh = issue(
        db, "beneficiary", beneficiary.id, vault.id, beneficiary.contact_revision
    )
    record_audit(db, vault.id, "beneficiary", beneficiary.id, "invite.accept", {})
    db.commit()

    # Cookies carry both tokens; JSON carries none.
    from services.cookies import set_beneficiary_session

    set_beneficiary_session(response, access_token, raw_refresh)

    return InvitationAcceptOut(
        message="Invitation accepted. You can now access the vault.",
        beneficiary_id=beneficiary.id,
    )


@public_router.post("/invitation/status")
def check_invitation_status(data: InvitationCredential, db: Session = Depends(get_db)):
    """Check invitation status without accepting (minimal disclosure)."""
    beneficiary = _find_by_invite(db, data.token)

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
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Renew a beneficiary session from its refresh cookie.

    Unlike the old flow, this does NOT require a still-valid access JWT: the
    single-use refresh credential (HttpOnly cookie) is the credential. Each
    use rotates both the session and the refresh credential.
    """
    raw_refresh = request.cookies.get(get_settings().session_cookie_name_beneficiary_refresh)
    if not raw_refresh:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    from services.sessions import rotate

    family, (access_token, new_raw) = rotate(db, raw_refresh, "beneficiary")
    beneficiary = db.get(Beneficiary, family.principal_id)
    db.commit()

    from services.cookies import set_beneficiary_session

    set_beneficiary_session(response, access_token, new_raw)

    return SessionCreateOut(
        message="Session created",
        beneficiary_id=beneficiary.id,
    )


@router.post("/revoke")
def revoke_beneficiary_session(
    request: Request,
    response: Response,
    current_beneficiary: Beneficiary = Depends(require_beneficiary),
    db: Session = Depends(get_db),
):
    """Revoke the calling beneficiary session (clears jti + refresh, clears cookies)."""
    from services.sessions import revoke_cookie

    revoke_cookie(
        db,
        request.cookies.get(get_settings().session_cookie_name_beneficiary_refresh),
        "beneficiary",
    )
    from services.cookies import clear_beneficiary_session

    clear_beneficiary_session(response)
    record_audit(
        db,
        current_beneficiary.vault_id,
        "beneficiary",
        current_beneficiary.id,
        "session.revoke",
        {},
    )
    db.commit()
    return {"message": "Session revoked"}


@router.post("/revoke-all")
def revoke_all_beneficiary_sessions(
    response: Response,
    current_beneficiary: Beneficiary = Depends(require_beneficiary),
    db: Session = Depends(get_db),
):
    from services.cookies import clear_beneficiary_session
    from services.sessions import revoke_beneficiary
    from services.trigger_service import lock_status

    lock_status(db, current_beneficiary.vault_id)
    revoke_beneficiary(db, current_beneficiary)
    record_audit(
        db,
        current_beneficiary.vault_id,
        "beneficiary",
        current_beneficiary.id,
        "session.revoke_all",
        {},
    )
    db.commit()
    clear_beneficiary_session(response)
    return {"message": "All beneficiary sessions revoked"}


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

    return AccessStatusOut(
        vault_status=vault_state,
        vault_name=vault.name,
        share_index=current_beneficiary.share_index,
        recovery_threshold=int(getattr(vault, "recovery_threshold", None) or 2),
        recovery_total=int(getattr(vault, "recovery_total", None) or 3),
        recovery_generation=getattr(vault, "recovery_generation", None),
        beneficiary_id=current_beneficiary.id,
        material_revision=vault.material_revision,
    )


@router.post("/share")
def submit_share():
    """Removed: the server cannot verify shares it must never see.

    Share-hash tracking was deleted — a fingerprint the backend can neither
    verify nor reconstruct provides no security benefit. Abuse protection
    lives in strict rate limits on session creation, status, and message
    retrieval, plus a client-side failed-attempt counter. Gone in 410 style:
    """
    raise HTTPException(status_code=410, detail="Share submission removed; reconstruct locally")


class RecoveryMessageMeta(BaseModel):
    id: int
    label: str
    category: str | None = None
    created_at: str


class RecoveryMessageDetail(BaseModel):
    id: int
    label: str
    ciphertext: str
    wrapped_mek: str
    crypto_metadata: dict
    crypto_version: int
    category: str | None = None
    created_at: str


def _require_triggered(db: Session, vault_id: int) -> None:
    vs = db.query(VaultStatus).filter(VaultStatus.vault_id == vault_id).first()
    if not vs or vs.state != "triggered":
        raise HTTPException(status_code=403, detail="Vault not triggered")


@router.get("/messages", response_model=list[RecoveryMessageMeta])
def list_recovery_messages(
    before_id: int | None = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=100),
    current_beneficiary: Beneficiary = Depends(require_beneficiary),
    db: Session = Depends(get_db),
):
    """List message metadata for beneficiary recovery (TRIGGERED only).

    Returns ciphertext-free metadata; fetch each message to get its
    ciphertext + wrapped MEK for local decryption. Never plaintext.
    """
    vault = _get_vault(db, current_beneficiary)
    _require_triggered(db, vault.id)
    rows = (
        db.query(
            VaultMessage.id, VaultMessage.label, VaultMessage.category, VaultMessage.created_at
        )
        .filter(VaultMessage.vault_id == vault.id)
        .filter(VaultMessage.id < before_id if before_id else True)
        .order_by(VaultMessage.id.desc())
        .limit(limit)
        .all()
    )
    return [
        RecoveryMessageMeta(
            id=m.id,
            label=m.label,
            category=m.category,
            created_at=m.created_at.isoformat() if m.created_at else "",
        )
        for m in rows
    ]


@router.get("/messages/{message_id}", response_model=RecoveryMessageDetail)
def get_recovery_message(
    message_id: int,
    current_beneficiary: Beneficiary = Depends(require_beneficiary),
    db: Session = Depends(get_db),
):
    """Get one message's ciphertext + wrapped MEK (TRIGGERED only, vault-scoped)."""
    vault = _get_vault(db, current_beneficiary)
    _require_triggered(db, vault.id)
    message = (
        db.query(VaultMessage)
        .filter(VaultMessage.id == message_id, VaultMessage.vault_id == vault.id)
        .first()
    )
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    try:
        metadata = json.loads(message.crypto_metadata) if message.crypto_metadata else {}
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Stored crypto metadata is corrupt") from exc
    if not isinstance(metadata, dict):
        raise HTTPException(status_code=500, detail="Stored crypto metadata is corrupt")
    return RecoveryMessageDetail(
        id=message.id,
        label=message.label,
        ciphertext=message.ciphertext,
        wrapped_mek=message.wrapped_mek,
        crypto_metadata=metadata,
        crypto_version=message.crypto_version,
        category=message.category,
        created_at=message.created_at.isoformat() if message.created_at else "",
    )


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

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

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import get_settings
from deps import get_db, require_beneficiary, require_owner
from models import Beneficiary, User, Vault, VaultMessage, VaultStatus
from services.audit import record_audit
from services.auth import (
    BENEFICIARY_REFRESH_DAYS,
    BENEFICIARY_TOKEN_EXPIRE_MINUTES,
    create_access_token,
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
                .filter(Vault.user_id == current_user.id, Vault.is_primary == True)
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

    # Create beneficiary-scoped access token (explicit role, 30-minute life)
    vault = _get_vault(db, beneficiary)
    access_token = create_access_token(
        beneficiary.id,
        vault.id,
        role="beneficiary",
        expires_minutes=BENEFICIARY_TOKEN_EXPIRE_MINUTES,
    )
    record_audit(db, vault.id, "beneficiary", beneficiary.id, "invite.accept", {})
    db.commit()
    # Issue a single-use refresh credential (hash stored, raw in cookie only)
    raw_refresh = secrets.token_urlsafe(32)
    beneficiary.refresh_hash = hash_token(raw_refresh)
    beneficiary.refresh_expires_at = datetime.now(UTC) + timedelta(days=BENEFICIARY_REFRESH_DAYS)
    db.commit()

    # Cookies carry both tokens; JSON carries none.
    settings = get_settings()
    secure = settings.environment == "production"
    response.set_cookie(
        key=settings.session_cookie_name_beneficiary,
        value=access_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=30 * 60,
        path="/",
    )
    response.set_cookie(
        key=settings.session_cookie_name_beneficiary_refresh,
        value=raw_refresh,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
        path="/access",
    )

    return InvitationAcceptOut(
        message="Invitation accepted. You can now access the vault.",
        beneficiary_id=beneficiary.id,
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
    beneficiary = (
        db.query(Beneficiary).filter(Beneficiary.refresh_hash == hash_token(raw_refresh)).first()
    )
    if not beneficiary or beneficiary.invitation_status != "accepted":
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    exp = beneficiary.refresh_expires_at
    if exp is not None:
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        if datetime.now(UTC) > exp:
            raise HTTPException(status_code=401, detail="Invalid or expired session")

    vault = _get_vault(db, beneficiary)
    access_token = create_access_token(
        beneficiary.id,
        vault.id,
        role="beneficiary",
        expires_minutes=BENEFICIARY_TOKEN_EXPIRE_MINUTES,
    )
    # Rotate: old refresh dies with this use.
    new_raw = secrets.token_urlsafe(32)
    beneficiary.refresh_hash = hash_token(new_raw)
    beneficiary.refresh_expires_at = datetime.now(UTC) + timedelta(days=BENEFICIARY_REFRESH_DAYS)
    db.commit()

    settings = get_settings()
    secure = settings.environment == "production"
    response.set_cookie(
        key=settings.session_cookie_name_beneficiary,
        value=access_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=30 * 60,
        path="/",
    )
    response.set_cookie(
        key=settings.session_cookie_name_beneficiary_refresh,
        value=new_raw,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
        path="/access",
    )

    return SessionCreateOut(
        message="Session created",
        beneficiary_id=beneficiary.id,
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
        recovery_threshold=int(getattr(vault, "recovery_threshold", None) or 2),
        recovery_total=int(getattr(vault, "recovery_total", None) or 3),
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
        db.query(VaultMessage)
        .filter(VaultMessage.vault_id == vault.id)
        .order_by(VaultMessage.created_at.desc())
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

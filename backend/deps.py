"""Shared FastAPI dependencies — auth and DB session."""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from config import get_settings
from db import get_db
from models import Beneficiary, User
from services.auth import decode_access_token

__all__ = [
    "get_db",
    "get_current_user",
    "get_current_beneficiary",
    "require_owner",
    "require_beneficiary",
]


def _get_token_from_request(request: Request) -> str | None:
    """Extract JWT token from Authorization header or HttpOnly cookie."""
    # Try Authorization header first
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        parts = auth_header.split(" ", 1)
        if len(parts) == 2 and parts[1].strip():
            return parts[1].strip()

    # Try cookie (owner session)
    return request.cookies.get(get_settings().session_cookie_name_owner)


def _get_beneficiary_token_from_request(request: Request) -> str | None:
    """Extract JWT token from Authorization header or HttpOnly cookie for beneficiaries."""
    # Try Authorization header first
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        parts = auth_header.split(" ", 1)
        if len(parts) == 2 and parts[1].strip():
            return parts[1].strip()

    # Try cookie
    return request.cookies.get(get_settings().session_cookie_name_beneficiary)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Get current authenticated owner user from JWT token."""
    token = _get_token_from_request(request)
    if not token:
        return None

    try:
        payload = decode_access_token(token)
    except RuntimeError:
        return None
    if not payload:
        return None

    # No default: role must be explicitly owner (fail closed)
    if payload.get("role") != "owner":
        return None

    try:
        user_id = int(payload.get("sub", 0))
    except (TypeError, ValueError):
        return None
    if user_id <= 0:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    from services.sessions import valid_family

    sid = payload.get("jti")
    if sid:
        if not valid_family(db, sid, "owner", user_id):
            return None
    elif get_settings().environment == "production":
        return None
    return user


def get_current_beneficiary(request: Request, db: Session = Depends(get_db)) -> Beneficiary | None:
    """Get current authenticated beneficiary from JWT token."""
    token = _get_beneficiary_token_from_request(request)
    if not token:
        return None

    try:
        payload = decode_access_token(token)
    except RuntimeError:
        return None
    if not payload:
        return None

    if payload.get("role") != "beneficiary":
        return None

    try:
        # Beneficiary tokens have beneficiary_id in sub
        beneficiary_id = int(payload.get("sub", 0))
    except (TypeError, ValueError):
        return None
    if beneficiary_id <= 0:
        return None
    beneficiary = db.query(Beneficiary).filter(Beneficiary.id == beneficiary_id).first()
    if beneficiary is None:
        return None
    # Lifecycle gate: only accepted beneficiaries hold usable sessions.
    # Deleted rows already 401 via the lookup above.
    if beneficiary.invitation_status != "accepted":
        return None
    from services.sessions import valid_family

    family = (
        valid_family(db, payload.get("jti"), "beneficiary", beneficiary_id)
        if payload.get("jti")
        else None
    )
    if family:
        if (
            family.contact_revision != beneficiary.contact_revision
            or family.vault_id != beneficiary.vault_id
        ):
            return None
        return beneficiary
    from models import AuthSession

    if payload.get("jti") and db.get(AuthSession, payload["jti"]):
        return None
    if get_settings().environment == "production":
        return None
    # Server-side revocation: if a jti is bound, the token must present it.
    # A token presenting a jti with no bound counterpart was revoked.
    # Tokens and rows both without jti are pre-hardening legacy — accepted
    # until their next refresh binds one.
    bound = getattr(beneficiary, "session_jti", None)
    token_jti = payload.get("jti")
    if bound:
        if not token_jti or token_jti != bound:
            return None
    elif token_jti:
        return None
    return beneficiary


def require_owner(user: User | None = Depends(get_current_user)) -> User:
    """Dependency that requires an authenticated owner."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


def require_beneficiary(
    beneficiary: Beneficiary | None = Depends(get_current_beneficiary),
) -> Beneficiary:
    """Dependency that requires an authenticated beneficiary."""
    if beneficiary is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return beneficiary

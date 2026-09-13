"""Authentication service — password hashing, JWT tokens, session management."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from sqlalchemy.orm import Session

from config import get_settings
from models import RefreshToken

# Argon2id password hasher
ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

# JWT settings
JWT_ALGORITHM = "RS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 30
# Beneficiary sessions are short-lived and independent from owner sessions.
BENEFICIARY_TOKEN_EXPIRE_MINUTES = 30
BENEFICIARY_REFRESH_DAYS = 7


def _get_jwt_private_key() -> str:
    """Return JWT private key for signing, failing closed if misconfigured."""
    try:
        return get_settings().jwt_private_key()
    except Exception as exc:
        raise RuntimeError("JWT private key not configured") from exc


def _get_jwt_public_key() -> str:
    """Return JWT public key for verification, failing closed if misconfigured."""
    try:
        return get_settings().jwt_public_key()
    except Exception as exc:
        raise RuntimeError("JWT public key not configured") from exc


def hash_password(password: str) -> str:
    """Hash a password using Argon2id."""
    return ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its Argon2id hash."""
    try:
        ph.verify(password_hash, password)
        return True
    except Exception:
        return False


def hash_token(token: str) -> str:
    """Hash a high-entropy bearer token using SHA-256 for fast indexed lookups."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_refresh_token_hash() -> tuple[str, str]:
    """Generate a secure random refresh token and return its (hash, token)."""
    token = secrets.token_urlsafe(32)
    return hash_token(token), token


def create_access_token(
    user_id: int,
    vault_id: int | None,
    role: str,
    expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES,
) -> str:
    """Create a short-lived JWT access token. Role is required (no default).

    vault_id may be None for owners who have not set up a vault yet — routers
    fail closed (404 Vault not found) until setup provisions the primary vault.
    """
    if role not in ("owner", "beneficiary"):
        raise ValueError("role must be 'owner' or 'beneficiary'")
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=expires_minutes)
    payload = {
        "sub": str(user_id),
        "vault_id": vault_id,
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, _get_jwt_private_key(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: int, vault_id: int | None, db: Session) -> tuple[str, str]:
    """Create a new refresh token, store its hash, and return (token, token_hash)."""
    token_hash, token = generate_refresh_token_hash()
    family_id = secrets.token_urlsafe(16)
    expires_at = datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    refresh_token = RefreshToken(
        user_id=user_id,
        vault_id=vault_id,
        token_hash=token_hash,
        family_id=family_id,
        expires_at=expires_at,
    )
    db.add(refresh_token)
    db.commit()
    db.refresh(refresh_token)

    return token, token_hash


def rotate_refresh_token(refresh_token: RefreshToken, db: Session) -> str:
    """Rotate a refresh token: revoke old, create new in same family, and return raw token.

    Re-checks the revoked flag under the caller's row lock: if another worker
    rotated first, raises RefreshReuseError instead of minting a sibling.
    """
    db.refresh(refresh_token)
    if refresh_token.revoked_at is not None:
        raise RefreshReuseError(refresh_token.family_id)
    # Revoke current token
    refresh_token.revoked_at = datetime.now(UTC)

    # Create new token in same family
    token_hash, token = generate_refresh_token_hash()
    new_refresh = RefreshToken(
        user_id=refresh_token.user_id,
        vault_id=refresh_token.vault_id,
        token_hash=token_hash,
        family_id=refresh_token.family_id,
        expires_at=datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        replaced_by=None,
    )
    db.add(new_refresh)
    db.flush()  # populate new_refresh.id before linking

    # Link old to new
    refresh_token.replaced_by = new_refresh.id

    db.commit()
    db.refresh(new_refresh)

    return token


class RefreshReuseError(Exception):
    """Raised when a revoked (already-rotated) refresh token is presented."""


def verify_refresh_token(token: str, db: Session) -> RefreshToken | None:
    """Verify a refresh token via SHA-256 hash lookup in O(1) time.

    Raises RefreshReuseError if a revoked-but-replaced token is presented
    (possible theft) so callers can revoke the whole family.

    The row is locked (SELECT ... FOR UPDATE, no-op on SQLite) and the lock
    is held by the caller's session until rotate_refresh_token() commits, so
    concurrent refreshes with the same token serialize instead of double-use.
    Callers must use the SAME session for verify + rotate without committing
    in between.
    """
    token_h = hash_token(token)
    candidate = (
        db.query(RefreshToken).filter(RefreshToken.token_hash == token_h).with_for_update().first()
    )

    if candidate is None:
        return None

    if candidate.revoked_at is not None:
        # Reuse of a rotated/compromised token — signal theft.
        if candidate.replaced_by is not None:
            raise RefreshReuseError(candidate.family_id)
        return None
    if candidate.expires_at <= datetime.now(UTC):
        return None
    return candidate


def revoke_refresh_token_family(family_id: str, db: Session) -> None:
    """Revoke all tokens in a family (used on logout/security event)."""
    tokens = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.family_id == family_id,
            RefreshToken.revoked_at.is_(None),
        )
        .all()
    )
    for rt in tokens:
        rt.revoked_at = datetime.now(UTC)
    db.commit()


def decode_access_token(token: str) -> dict | None:
    """Decode and validate an access token using configured public key."""
    try:
        public_key = _get_jwt_public_key()
        payload = jwt.decode(token, public_key, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        if payload.get("role") not in ("owner", "beneficiary"):
            return None
        if "sub" not in payload or "vault_id" not in payload:
            return None
        return payload
    except (jwt.PyJWTError, RuntimeError):
        pass
    return None

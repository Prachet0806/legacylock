"""Authentication routes — register, verify, login, logout, token refresh, me."""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import get_settings
from deps import get_db, require_owner
from models import User, Vault
from services.audit import record_audit
from services.auth import (
    RefreshReuseError,
    create_access_token,
    create_refresh_token,
    hash_password,
    revoke_refresh_token_family,
    rotate_refresh_token,
    verify_password,
    verify_refresh_token,
)

# Argon2id hash of a dummy secret. Verified (and discarded) on unknown-email
# logins so existent vs non-existent accounts take the same time.
_DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$lVyi01Da0+4qcgurGVRIjQ$aDX//0PsB+UKqM5W/ZRGk1tB5lldLeBGf0OHvtdw2dI"

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=12, max_length=256)


class LoginResponse(BaseModel):
    # Tokens travel via HttpOnly cookies only — never in JSON bodies.
    message: str = "Logged in"
    expires_in: int = 900


class RefreshResponse(BaseModel):
    # Tokens travel via HttpOnly cookies only — never in JSON bodies.
    message: str = "Token refreshed"
    expires_in: int = 900


class UserResponse(BaseModel):
    id: int
    email: str
    created_at: str
    email_verified: bool = False


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=12, max_length=256)
    invite_code: str = Field(..., min_length=8, max_length=256)


class RegisterResponse(BaseModel):
    message: str = "If eligible, a verification email has been sent"


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=256)


class ResendVerificationRequest(BaseModel):
    email: EmailStr


def _is_production() -> bool:
    return get_settings().environment == "production"


def set_auth_cookies(
    response: Response, access_token: str, refresh_token: str, secure: bool = False
) -> None:
    """Set HttpOnly cookies for access and refresh tokens (Option A: refresh cookie-only)."""
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name_owner,
        value=access_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=15 * 60,  # 15 minutes
        path="/",
    )
    response.set_cookie(
        key=settings.session_cookie_name_owner_refresh,
        value=refresh_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=30 * 24 * 60 * 60,  # 30 days
        # Path=/ so the cookie is sent through the documented /api edge
        # prefix (browser sees /api/auth/refresh; Path=/auth would not match).
        path="/",
    )


def clear_auth_cookies(response: Response, secure: bool = False) -> None:
    """Clear auth cookies on logout (flags must match set_cookie)."""
    settings = get_settings()
    response.delete_cookie(
        settings.session_cookie_name_owner, path="/", secure=secure, httponly=True, samesite="lax"
    )
    response.delete_cookie(
        settings.session_cookie_name_owner_refresh,
        path="/",
        secure=secure,
        httponly=True,
        samesite="lax",
    )


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(
    data: RegisterRequest,
    db: Session = Depends(get_db),
) -> RegisterResponse:
    """Gated self-service registration (B-spec) + Resend verification.

    Fail-closed when REGISTRATION_INVITE_CODE is empty. Invite is checked
    first (constant-time) so outsiders learn nothing about email existence.
    Always returns the same 201 message — enumeration-safe for new, existing
    unverified (re-send), and existing verified (no-op) cases.
    """
    from services.email_verification import issue_verification

    settings = get_settings()
    expected = settings.registration_invite_code or ""
    if not expected.strip() or not secrets.compare_digest(data.invite_code, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid invitation",
        )

    email = str(data.email).strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(email=email, password_hash=hash_password(data.password))
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # Lost a concurrent race — fall through to the safe re-send path.
            user = db.query(User).filter(User.email == email).first()
            if user is None:
                return RegisterResponse()
        else:
            db.refresh(user)
            vault = Vault(user_id=user.id, name="Primary Vault", is_primary=True)
            db.add(vault)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
            record_audit(db, None, "owner", user.id, "auth.register", {})
            db.commit()
            await issue_verification(db, user)
            return RegisterResponse()

    # Existing account: re-send verification if still unverified, else no-op.
    # Same response either way — no enumeration oracle.
    try:
        if user.email_verified_at is None:
            await issue_verification(db, user)
    except Exception:
        pass
    return RegisterResponse()


@router.post("/verify-email")
def verify_email(
    data: VerifyEmailRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Redeem a single-use verification token (generic error, no oracle)."""
    from services.email_verification import consume_verification

    user = consume_verification(db, data.token)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    return {"message": "Email verified"}


class TestIssueVerificationRequest(BaseModel):
    email: EmailStr


@router.post("/test-issue-verification")
async def test_issue_verification(
    data: TestIssueVerificationRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """E2E-only: issue a verification link and return it (no mailbox in tests).

    404 in production. Mirrors the backend test helper that captures the
    emailed link — the raw token is otherwise unrecoverable (hash-only).
    """
    from services.email_verification import issue_verification, verification_link

    if get_settings().environment == "production":
        raise HTTPException(status_code=404, detail="Not found")
    email = str(data.email).strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user is None or user.email_verified_at is not None:
        raise HTTPException(status_code=404, detail="No unverified account for this email")
    # No cooldown here: this IS the test mailbox, not the public resend path.
    raw = await issue_verification(db, user)
    return {"link": verification_link(raw)}


@router.post("/resend-verification")
async def resend_verification(
    data: ResendVerificationRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Re-send verification link. Always 200 — response-level enumeration resistant.

    Per-email 5-minute cooldown supplements IP rate limits (VerificationCooldown
    maps to the same generic success so the cooldown itself is not an oracle).
    """
    from services.email_verification import VerificationCooldown, issue_verification

    email = str(data.email).strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user is not None and user.email_verified_at is None:
        try:
            await issue_verification(db, user, enforce_cooldown=True)
        except VerificationCooldown:
            pass
        except Exception:
            pass
    return {"message": "If the account needs verification, an email has been sent"}


@router.post("/login", response_model=LoginResponse)
def login(
    data: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """Authenticate user. Refresh token is cookie-only (never in JSON)."""
    email = str(data.email).strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        # Constant-time: burn the same Argon2id cost as a real check.
        verify_password(data.password, _DUMMY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if user.email_verified_at is None:
        record_audit(db, None, "owner", user.id, "auth.login_blocked_unverified", {})
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified",
        )

    # Authentication has no domain side effects: vault provisioning happens
    # explicitly at setup (PUT /vault/crypto-material), not here.
    vault = db.query(Vault).filter(Vault.user_id == user.id, Vault.is_primary == True).first()

    access_token = create_access_token(user.id, vault.id if vault else None, role="owner")
    refresh_token, _ = create_refresh_token(user.id, vault.id if vault else None, db)

    secure = _is_production()
    set_auth_cookies(response, access_token, refresh_token, secure)
    record_audit(db, vault.id if vault else None, "owner", user.id, "auth.login", {})
    db.commit()

    return LoginResponse()


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Logout: revoke the refresh family in the HttpOnly cookie, clear cookies.

    Mass-revoke requires possession of the refresh cookie itself: a stolen
    short-lived access token alone must not be able to nuke all sessions.
    """
    secure = _is_production()
    revoked = False
    # Canonical path: refresh token from HttpOnly cookie (Option A)
    raw_refresh = request.cookies.get(get_settings().session_cookie_name_owner_refresh)
    if raw_refresh:
        try:
            rt = verify_refresh_token(raw_refresh, db)
        except RefreshReuseError as exc:
            try:
                revoke_refresh_token_family(str(exc.args[0]) if exc.args else "", db)
            except Exception:
                pass
            rt = None
        if rt:
            try:
                revoke_refresh_token_family(rt.family_id, db)
                revoked = True
                record_audit(db, rt.vault_id, "owner", rt.user_id, "auth.logout", {})
                db.commit()
            except Exception:
                db.rollback()

    clear_auth_cookies(response, secure)
    return {"message": "Logged out successfully"}


@router.post("/refresh", response_model=RefreshResponse)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> RefreshResponse:
    """Rotate refresh token from HttpOnly cookie and issue new access token."""
    raw = request.cookies.get(get_settings().session_cookie_name_owner_refresh)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    try:
        rt = verify_refresh_token(raw, db)
    except RefreshReuseError as exc:
        # Possible theft: revoke entire family
        try:
            revoke_refresh_token_family(str(exc.args[0]) if exc.args else "", db)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    if not rt:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Rotate refresh token
    new_rt = rotate_refresh_token(rt, db)

    # Resolve the primary vault (may be absent pre-setup — session stays valid)
    vault = db.query(Vault).filter(Vault.user_id == rt.user_id, Vault.is_primary == True).first()

    access_token = create_access_token(rt.user_id, vault.id if vault else None, role="owner")

    secure = _is_production()
    set_auth_cookies(response, access_token, new_rt, secure)

    return RefreshResponse()


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(require_owner)) -> UserResponse:
    """Get current authenticated user info."""
    return UserResponse(
        id=user.id,
        email=user.email,
        created_at=user.created_at.isoformat() if user.created_at else "",
        email_verified=user.email_verified_at is not None,
    )

"""Authentication routes — login, logout, token refresh, current user."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from config import get_settings
from deps import get_db, require_owner
from models import User, Vault
from services.audit import record_audit
from services.auth import (
    RefreshReuseError,
    create_access_token,
    create_refresh_token,
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
        path="/auth",
    )


def clear_auth_cookies(response: Response, secure: bool = False) -> None:
    """Clear auth cookies on logout (flags must match set_cookie)."""
    settings = get_settings()
    response.delete_cookie(
        settings.session_cookie_name_owner, path="/", secure=secure, httponly=True, samesite="lax"
    )
    response.delete_cookie(
        settings.session_cookie_name_owner_refresh,
        path="/auth",
        secure=secure,
        httponly=True,
        samesite="lax",
    )


@router.post("/login", response_model=LoginResponse)
def login(
    data: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """Authenticate user. Refresh token is cookie-only (never in JSON)."""
    user = db.query(User).filter(User.email == data.email).first()
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
    )

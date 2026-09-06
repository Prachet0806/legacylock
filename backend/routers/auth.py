"""Authentication routes — login, logout, token refresh, current user."""

from datetime import UTC, datetime
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from models import User, Vault, RefreshToken
from services.auth import (
    create_access_token,
    create_refresh_token,
    verify_password,
    verify_refresh_token,
    revoke_refresh_token_family,
    decode_access_token,
    rotate_refresh_token,
)
from deps import get_db, require_owner

router = APIRouter(prefix="/auth", tags=["auth"])

security = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: str
    created_at: str


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Set HttpOnly cookies for access and refresh tokens."""
    response.set_cookie(
        key="legacylock_owner_session",
        value=access_token,
        httponly=True,
        secure=False,  # Set to True in production with HTTPS
        samesite="lax",
        max_age=15 * 60,  # 15 minutes
        path="/",
    )
    response.set_cookie(
        key="legacylock_owner_refresh",
        value=refresh_token,
        httponly=True,
        secure=False,  # Set to True in production with HTTPS
        samesite="lax",
        max_age=30 * 24 * 60 * 60,  # 30 days
        path="/auth",
    )


def clear_auth_cookies(response: Response) -> None:
    """Clear auth cookies on logout."""
    response.delete_cookie("legacylock_owner_session", path="/")
    response.delete_cookie("legacylock_owner_refresh", path="/auth")


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> int:
    """Extract user ID from access token."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    from services.auth import decode_access_token
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return int(payload["sub"])


def get_current_user(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(lambda: next(get_db())),
) -> User:
    """Get current authenticated user."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user


@router.post("/login", response_model=LoginResponse)
def login(
    data: LoginRequest,
    response: Response,
    db: Session = Depends(lambda: next(get_db())),
) -> LoginResponse:
    """Authenticate user and return access + refresh tokens."""
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    
    # Get or create vault for user
    vault = db.query(Vault).filter(Vault.user_id == user.id).first()
    if not vault:
        vault = Vault(user_id=user.id, name="Primary Vault")
        db.add(vault)
        db.commit()
        db.refresh(vault)
    
    access_token = create_access_token(user.id, vault.id)
    refresh_token, _ = create_refresh_token(user.id, vault.id, db)
    
    set_auth_cookies(response, access_token, refresh_token)
    
    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/logout")
def logout(
    response: Response,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Logout user and revoke refresh token family."""
    if credentials:
        payload = decode_access_token(credentials.credentials)
        if payload:
            user_id = int(payload["sub"])
            refresh_tokens = db.query(RefreshToken).filter(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            ).all()
            for rt in refresh_tokens:
                rt.revoked_at = datetime.now(UTC)
            db.commit()

    clear_auth_cookies(response)
    return {"message": "Logged out successfully"}


@router.post("/refresh", response_model=RefreshResponse)
def refresh(
    data: RefreshRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> RefreshResponse:
    """Rotate refresh token and issue new access token."""
    rt = verify_refresh_token(data.refresh_token, db)
    if not rt:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Rotate refresh token
    new_rt = rotate_refresh_token(rt, db)

    # Create new access token
    vault = db.query(Vault).filter(Vault.user_id == rt.user_id).first()
    if not vault:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vault not found",
        )

    access_token = create_access_token(rt.user_id, vault.id)

    set_auth_cookies(response, access_token, new_rt)

    return RefreshResponse(
        access_token=access_token,
        refresh_token=new_rt,
    )


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(require_owner)) -> UserResponse:
    """Get current authenticated user info."""
    return UserResponse(
        id=user.id,
        email=user.email,
        created_at=user.created_at.isoformat() if user.created_at else "",
    )
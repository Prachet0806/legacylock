from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo checkout root (this file lives at <root>/backend/config.py).
# Deployment rule: prefer absolute/container paths via JWT_*_KEY_PATH env
# (e.g. /run/secrets/jwt_private.pem); relative paths resolve against the
# backend package dir below for local development only.
REPO_ROOT = Path(__file__).parent.parent
BACKEND_DIR = REPO_ROOT / "backend"


class Settings(BaseSettings):
    environment: Literal["development", "test", "production"] = "development"
    allowed_origins: str = "http://localhost:3000"
    database_url: str
    session_secret: str
    session_cookie_name_owner: str = "legacylock_owner_session"
    session_cookie_name_owner_refresh: str = "legacylock_owner_refresh"
    session_cookie_name_beneficiary: str = "legacylock_beneficiary_session"
    session_cookie_name_beneficiary_refresh: str = "legacylock_beneficiary_refresh"
    frontend_url: str = "http://localhost:3000"
    trusted_proxies: str = ""
    heartbeat_enabled: bool = True
    # JWT RS256 keys (paths relative to backend/ or absolute)
    jwt_private_key_path: str = "keys/jwt_private.pem"
    jwt_public_key_path: str = "keys/jwt_public.pem"
    # Gated self-service registration (B-spec): empty = disabled (fail-closed).
    # Distribute the code out-of-band; rotation = new value + restart.
    registration_invite_code: str = ""
    # Email delivery via Resend (empty = mock-log). Replaces SendGrid.
    resend_api_key: str = ""
    notification_email_from: str = "noreply@legacylock.app"
    email_verification_ttl_hours: int = 24

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("session_secret")
    @classmethod
    def _secret_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SESSION_SECRET must be >= 32 characters")
        return v

    def trusted_proxy_list(self) -> list[str]:
        if not self.trusted_proxies.strip():
            return []
        return [p.strip() for p in self.trusted_proxies.split(",") if p.strip()]

    def frontend_origin(self) -> str:
        return self.frontend_url.rstrip("/")

    def registration_enabled(self) -> bool:
        return bool(self.registration_invite_code.strip())

    def jwt_private_key(self) -> str:
        """Load RSA private key for JWT signing."""
        path = Path(self.jwt_private_key_path)
        if not path.is_absolute():
            path = BACKEND_DIR / path
        return path.read_text()

    def jwt_public_key(self) -> str:
        """Load RSA public key for JWT verification."""
        path = Path(self.jwt_public_key_path)
        if not path.is_absolute():
            path = BACKEND_DIR / path
        return path.read_text()


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

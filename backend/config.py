import base64
from functools import lru_cache
from ipaddress import ip_network
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo checkout root (this file lives at <root>/backend/config.py).
# Deployment rule: prefer absolute/container paths via JWT_*_KEY_PATH env
# (e.g. /run/secrets/jwt_private.pem); relative paths resolve against the
# backend package dir below for local development only.
REPO_ROOT = Path(__file__).parent.parent
BACKEND_DIR = REPO_ROOT / "backend"


def _is_https_origin(value: str) -> bool:
    parsed = urlsplit(value)
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and parsed.path in ("", "/")
        and not parsed.query
        and not parsed.fragment
        and parsed.hostname not in {"localhost", "127.0.0.1", "app.example.com"}
    )


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
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    heartbeat_enabled: bool = True
    release_hold: bool = False
    delivery_enabled: bool = True
    delivery_payload_key: str = ""
    delivery_payload_key_id: str = "v1"
    delivery_payload_keys: str = "{}"
    auth_epoch: str = "initial"
    sms_enabled: bool = False
    background_in_api: bool = True
    db_pool_size: int = Field(default=3, ge=1, le=20)
    db_max_overflow: int = Field(default=0, ge=0, le=20)
    db_pool_timeout: int = Field(default=10, ge=1, le=60)
    max_beneficiaries_per_vault: int = Field(default=25, ge=1, le=255)
    max_messages_per_vault: int = Field(default=100, ge=1, le=10000)
    migrated_schema_only: bool = False
    operations_token: str = ""
    # JWT RS256 keys (paths relative to backend/ or absolute)
    jwt_private_key_path: str = "keys/jwt_private.pem"
    jwt_public_key_path: str = "keys/jwt_public.pem"
    jwt_private_key_b64: SecretStr | None = None
    jwt_public_key_b64: SecretStr | None = None
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

    def validate_production(self) -> None:
        """Reject implicit development defaults before any production work starts."""
        if self.environment != "production":
            return
        required = {
            "release_hold",
            "delivery_enabled",
            "auth_epoch",
            "background_in_api",
            "frontend_url",
            "allowed_origins",
            "allowed_hosts",
            "heartbeat_enabled",
            "sms_enabled",
            "notification_email_from",
        }
        missing = required - self.model_fields_set
        if missing:
            names = ", ".join(sorted(missing))
            raise RuntimeError(f"Explicit production settings required: {names}")
        if self.background_in_api or not self.heartbeat_enabled or self.sms_enabled:
            raise RuntimeError(
                "Production requires an independent checker/delivery worker and SMS disabled"
            )
        if not self.auth_epoch.strip() or self.auth_epoch == "initial":
            raise RuntimeError("Production AUTH_EPOCH must be a fresh explicit value")
        self._validate_production_network()
        if not self.resend_api_key or not self.notification_email_from.strip():
            raise RuntimeError("Production email credentials and sender are required")

    def _validate_production_network(self) -> None:
        if not _is_https_origin(self.frontend_url):
            raise RuntimeError("Production FRONTEND_URL must be the exact HTTPS application origin")
        origins = [
            value.strip().rstrip("/") for value in self.allowed_origins.split(",") if value.strip()
        ]
        if origins != [self.frontend_origin()] or not _is_https_origin(origins[0]):
            raise RuntimeError("Production ALLOWED_ORIGINS must equal the HTTPS frontend origin")
        hosts = [value.strip().lower() for value in self.allowed_hosts.split(",") if value.strip()]
        invalid_hosts = {"*", "testserver"}
        if not hosts or any(
            value in invalid_hosts
            or "example.com" in value
            or "*" in value
            or "://" in value
            or "/" in value
            for value in hosts
        ):
            raise RuntimeError("Production ALLOWED_HOSTS must name the deployed API hosts")
        if not any(value not in {"localhost", "127.0.0.1"} for value in hosts):
            raise RuntimeError("Production ALLOWED_HOSTS must include a deployed API host")
        try:
            for value in self.trusted_proxy_list():
                ip_network(value, strict=False)
        except ValueError as exc:
            raise RuntimeError("TRUSTED_PROXIES must contain valid CIDRs") from exc

    def frontend_origin(self) -> str:
        return self.frontend_url.rstrip("/")

    def registration_enabled(self) -> bool:
        return bool(self.registration_invite_code.strip())

    def jwt_private_key(self) -> str:
        """Load RSA private key for JWT signing."""
        if self.jwt_private_key_b64 is not None:
            return self._decode_jwt_key(self.jwt_private_key_b64)
        path = Path(self.jwt_private_key_path)
        if not path.is_absolute():
            path = BACKEND_DIR / path
        return path.read_text()

    def jwt_public_key(self) -> str:
        """Load RSA public key for JWT verification."""
        if self.jwt_public_key_b64 is not None:
            return self._decode_jwt_key(self.jwt_public_key_b64)
        path = Path(self.jwt_public_key_path)
        if not path.is_absolute():
            path = BACKEND_DIR / path
        return path.read_text()

    @staticmethod
    def _decode_jwt_key(value: SecretStr) -> str:
        try:
            return base64.b64decode(value.get_secret_value(), validate=True).decode("ascii")
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError("Invalid base64-encoded JWT PEM") from exc


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).parent.parent


class Settings(BaseSettings):
    environment: str = "development"
    allowed_origins: str = "http://localhost:3000"
    database_url: str
    session_secret: str
    session_cookie_name_owner: str = "legacylock_owner_session"
    session_cookie_name_beneficiary: str = "legacylock_beneficiary_session"
    frontend_url: str = "http://localhost:3000"
    trusted_proxies: str = ""
    heartbeat_enabled: bool = True
    # JWT RS256 keys (paths relative to backend/ or absolute)
    jwt_private_key_path: str = "keys/jwt_private.pem"
    jwt_public_key_path: str = "keys/jwt_public.pem"

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        case_sensitive=False,
        extra="ignore",
    )

    def trusted_proxy_list(self) -> list[str]:
        if not self.trusted_proxies.strip():
            return []
        return [p.strip() for p in self.trusted_proxies.split(",") if p.strip()]

    def frontend_origin(self) -> str:
        return self.frontend_url.rstrip("/")

    def jwt_private_key(self) -> str:
        """Load RSA private key for JWT signing."""
        path = Path(self.jwt_private_key_path)
        if not path.is_absolute():
            path = ROOT_DIR / "backend" / path
        return path.read_text()

    def jwt_public_key(self) -> str:
        """Load RSA public key for JWT verification."""
        path = Path(self.jwt_public_key_path)
        if not path.is_absolute():
            path = ROOT_DIR / "backend" / path
        return path.read_text()


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

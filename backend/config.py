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


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

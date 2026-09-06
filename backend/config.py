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

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

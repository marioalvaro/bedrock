from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    data_dir: Path = Path("../data")
    database_url: str | None = None
    sec_user_agent: str | None = None
    fred_api_key: str | None = None
    app_password_hash: str = ""
    # Required, with no default: a built-in one would be a published key (G10).
    session_secret: str
    session_idle_minutes: int = 720
    cookie_secure: bool = False
    static_dir: Path | None = None

    @field_validator("database_url", "sec_user_agent", "fred_api_key", "static_dir", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        # `KEY=` (as shipped in .env.example, or STATIC_DIR="" in the dev profile, since
        # Docker cannot unset an inherited ENV) means "not configured", not "" (G9).
        return None if value == "" else value

    @field_validator("session_secret")
    @classmethod
    def _session_secret_must_be_set(cls, value: str) -> str:
        # A blank secret signs cookies with a key anyone can reproduce (G10).
        if not value.strip():
            raise ValueError("SESSION_SECRET must not be blank")
        return value

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir}/bedrock.db"


@lru_cache
def load_settings() -> Settings:
    """Settings from the environment, for code that runs outside a request (CLI, Alembic)."""
    return Settings()

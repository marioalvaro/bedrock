from functools import lru_cache
from pathlib import Path

from fastapi import Request
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    data_dir: Path = Path("../data")
    database_url: str | None = None
    sec_user_agent: str | None = None
    fred_api_key: str | None = None
    app_password_hash: str = ""
    session_secret: str = "dev-insecure-change-me"
    session_idle_minutes: int = 720
    cookie_secure: bool = False
    static_dir: Path | None = None

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir}/bedrock.db"


@lru_cache
def load_settings() -> Settings:
    """Settings from the environment, for code that runs outside a request (CLI, Alembic)."""
    return Settings()


def get_settings(request: Request) -> Settings:
    """The settings the running app was built with."""
    settings: Settings = request.app.state.settings
    return settings

from functools import lru_cache
from pathlib import Path

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
def get_settings() -> Settings:
    return Settings()

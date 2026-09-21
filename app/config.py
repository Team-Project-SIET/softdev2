from functools import lru_cache

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    database_url: PostgresDsn
    sql_echo: bool = False
    depot_name: str = "Main Depot"
    depot_latitude: float = Field(default=13.756331, ge=-90, le=90)
    depot_longitude: float = Field(default=100.501762, ge=-180, le=180)
    line_channel_access_token: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()

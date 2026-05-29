from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Wix Scanner Backend"
    environment: str = "development"
    api_v1_prefix: str = "/api"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    # Secret used to sign and verify bootstrap QR payloads.
    # Must be set to a strong random value in production.
    bootstrap_secret: str = "dev-bootstrap-secret-change-in-production"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="WIX_SCANNER_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

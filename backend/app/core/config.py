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
    wix_mock_mode: bool = True
    wix_base_url: str = "https://www.wixapis.com"
    wix_checkin_path: str = "/events/v1/tickets/check-in"
    wix_api_token: str = ""
    wix_timeout_ms: int = 2500
    wix_max_retries: int = 3
    wix_retry_base_ms: int = 150
    wix_retry_max_ms: int = 1500

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="WIX_SCANNER_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

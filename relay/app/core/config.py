from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Wix Scanner Relay"
    environment: str = "development"
    api_v1_prefix: str = "/api"
    host: str = "0.0.0.0"
    port: int = 9000
    # Relay authentication token (bearer token sent to cloud backend).
    relay_auth_token: str = "dev-relay-auth-token-change-in-production"
    relay_signing_secret: str = "dev-relay-signing-secret-change-in-production"
    relay_instance_id: str = "relay-dev-1"
    relay_protocol_version: str = "2026-05-29"
    # Cloud backend base URL for forwarding scans.
    cloud_base_url: str = "http://localhost:8000/api"
    # Request timeout for cloud backend calls.
    cloud_request_timeout_ms: int = 5000
    # Local queue persistence (SQLite).
    queue_db_path: str = "./data/relay_queue.db"
    # Forwarder backoff timing (milliseconds).
    forwarder_backoff_base_ms: int = 1000
    forwarder_backoff_max_ms: int = 30000
    forwarder_poll_interval_s: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="WIX_RELAY_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

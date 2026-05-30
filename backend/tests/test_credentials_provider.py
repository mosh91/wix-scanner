from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.credentials import (
    EncryptedDatabaseCredentialProvider,
    EnvironmentCredentialProvider,
    get_credential_provider,
)


def test_credential_provider_env_mode_loads_token_from_settings() -> None:
    settings = Settings(
        wix_mock_mode=False,
        credential_provider_mode="env",
        wix_api_token="env-token-123",
    )

    provider = get_credential_provider(settings)

    assert isinstance(provider, EnvironmentCredentialProvider)
    assert provider.get_wix_api_token() == "env-token-123"


def test_credential_provider_db_mode_returns_decrypted_token(tmp_path: Path) -> None:
    db_path = tmp_path / "credentials.db"
    settings = Settings(
        wix_mock_mode=False,
        credential_provider_mode="db",
        credential_db_path=str(db_path),
        credential_encryption_key="test-encryption-key",
    )

    provider = get_credential_provider(settings)
    assert isinstance(provider, EncryptedDatabaseCredentialProvider)
    provider.set_wix_api_token("db-secret-token")

    # Credential is persisted encrypted and only decrypted on retrieval.
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT encrypted_value FROM secret_credential WHERE provider = ? AND key_name = ?",
            ("wix", "api_token"),
        ).fetchone()
    assert row is not None
    assert row[0] != "db-secret-token"

    loaded = provider.get_wix_api_token()
    assert loaded == "db-secret-token"


def test_debug_logging_redacts_secret_values(caplog: pytest.LogCaptureFixture) -> None:  # type: ignore[name-defined]
    settings = Settings(
        credential_provider_mode="env",
        wix_api_token="super-secret-value",
    )
    provider = EnvironmentCredentialProvider(settings)

    caplog.set_level(logging.DEBUG)
    token = provider.get_wix_api_token()

    assert token == "super-secret-value"
    assert "super-secret-value" not in caplog.text
    previews = [getattr(record, "token_preview", None) for record in caplog.records]
    assert "su***ue" in previews

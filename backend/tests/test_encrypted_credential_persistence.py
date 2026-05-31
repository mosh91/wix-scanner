"""Tests for P2-US-07: Encrypted credential persistence in database.

Acceptance criteria covered:
  AC1 — DB stores encrypted blob and metadata only (no plaintext).
  AC2 — Unauthorized service path is denied (PermissionError).
  AC3 — Key rotation re-encrypts all records; credentials remain readable.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.credentials import (
    EncryptedDatabaseCredentialProvider,
    get_credential_provider,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db_settings(tmp_path: Path, *, key: str = "test-key", version: str = "v1") -> Settings:
    return Settings(
        wix_mock_mode=True,
        credential_provider_mode="db",
        credential_db_path=str(tmp_path / "creds.db"),
        credential_encryption_key=key,
        credential_key_version=version,
    )


def _raw_encrypted_value(db_path: Path) -> str:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT encrypted_value FROM secret_credential WHERE provider='wix' AND key_name='api_token'"
        ).fetchone()
    assert row is not None, "no credential row found"
    return str(row[0])


def _raw_key_version(db_path: Path) -> str:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT key_version FROM secret_credential WHERE provider='wix' AND key_name='api_token'"
        ).fetchone()
    assert row is not None, "no credential row found"
    return str(row[0])


# ---------------------------------------------------------------------------
# AC1 — DB stores encrypted blob and metadata only
# ---------------------------------------------------------------------------


def test_db_stores_encrypted_blob_not_plaintext(tmp_path: Path) -> None:
    settings = _db_settings(tmp_path)
    provider = get_credential_provider(settings)
    assert isinstance(provider, EncryptedDatabaseCredentialProvider)

    provider.set_wix_api_token("super-secret-api-token")

    raw = _raw_encrypted_value(Path(settings.credential_db_path))
    assert "super-secret-api-token" not in raw
    # Fernet tokens are recognisable as URL-safe base64 and typically start with 'gAAAAA'
    assert len(raw) > 20


def test_key_version_is_persisted_as_metadata(tmp_path: Path) -> None:
    settings = _db_settings(tmp_path, version="v2")
    provider = get_credential_provider(settings)
    assert isinstance(provider, EncryptedDatabaseCredentialProvider)

    provider.set_wix_api_token("token-for-v2")

    stored_version = _raw_key_version(Path(settings.credential_db_path))
    assert stored_version == "v2"


def test_encrypted_value_is_decryptable_via_authorised_provider(tmp_path: Path) -> None:
    settings = _db_settings(tmp_path)
    provider = get_credential_provider(settings)
    assert isinstance(provider, EncryptedDatabaseCredentialProvider)

    provider.set_wix_api_token("roundtrip-token")
    assert provider.get_wix_api_token() == "roundtrip-token"


# ---------------------------------------------------------------------------
# AC2 — Unauthorized service path raises PermissionError
# ---------------------------------------------------------------------------


def test_direct_instantiation_denies_read(tmp_path: Path) -> None:
    """Provider created without the factory sentinel is unauthorised."""
    settings = _db_settings(tmp_path)
    # First write via authorised factory so there is something to read.
    authorised = get_credential_provider(settings)
    assert isinstance(authorised, EncryptedDatabaseCredentialProvider)
    authorised.set_wix_api_token("should-not-be-readable")

    # Now create an instance directly (no factory sentinel) — read must be denied.
    unauthorised = EncryptedDatabaseCredentialProvider(settings)
    with pytest.raises(PermissionError):
        unauthorised.get_wix_api_token()


def test_direct_instantiation_denies_key_rotation(tmp_path: Path) -> None:
    settings = _db_settings(tmp_path)
    provider = get_credential_provider(settings)
    assert isinstance(provider, EncryptedDatabaseCredentialProvider)
    provider.set_wix_api_token("token")

    unauthorised = EncryptedDatabaseCredentialProvider(settings)
    with pytest.raises(PermissionError):
        unauthorised.rotate_key("new-key", "v2")


# ---------------------------------------------------------------------------
# AC3 — Key rotation re-encrypts all records; credentials remain readable
# ---------------------------------------------------------------------------


def test_rotate_key_re_encrypts_all_records(tmp_path: Path) -> None:
    settings = _db_settings(tmp_path, key="original-key", version="v1")
    provider = get_credential_provider(settings)
    assert isinstance(provider, EncryptedDatabaseCredentialProvider)

    provider.set_wix_api_token("pre-rotation-secret")
    encrypted_before = _raw_encrypted_value(Path(settings.credential_db_path))

    migrated = provider.rotate_key("rotated-key", "v2")
    assert migrated == 1

    encrypted_after = _raw_encrypted_value(Path(settings.credential_db_path))
    # Encrypted blob must differ after rotation.
    assert encrypted_before != encrypted_after

    # Key version metadata updated.
    assert _raw_key_version(Path(settings.credential_db_path)) == "v2"


def test_credentials_remain_readable_after_key_rotation(tmp_path: Path) -> None:
    settings = _db_settings(tmp_path, key="original-key", version="v1")
    provider = get_credential_provider(settings)
    assert isinstance(provider, EncryptedDatabaseCredentialProvider)

    provider.set_wix_api_token("post-rotation-readable")
    provider.rotate_key("rotated-key", "v2")

    assert provider.get_wix_api_token() == "post-rotation-readable"


def test_rotate_key_returns_zero_when_no_records(tmp_path: Path) -> None:
    settings = _db_settings(tmp_path)
    provider = get_credential_provider(settings)
    assert isinstance(provider, EncryptedDatabaseCredentialProvider)

    migrated = provider.rotate_key("new-key", "v2")
    assert migrated == 0

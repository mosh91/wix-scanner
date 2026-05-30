from __future__ import annotations

import base64
import hashlib
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from time import time

from app.core.config import Settings

logger = logging.getLogger(__name__)


def redact_secret(secret: str | None) -> str:
    if not secret:
        return "<empty>"
    if len(secret) <= 6:
        return "***"
    return f"{secret[:2]}***{secret[-2:]}"


def _derive_key_material(raw_key: str) -> bytes:
    digest = hashlib.sha256(raw_key.encode("utf-8")).digest()
    return digest


def _xor_crypt(payload: bytes, key_material: bytes) -> bytes:
    if not payload:
        return payload
    output = bytearray(len(payload))
    key_len = len(key_material)
    for idx, byte in enumerate(payload):
        output[idx] = byte ^ key_material[idx % key_len]
    return bytes(output)


@dataclass(frozen=True)
class CredentialRecord:
    provider: str
    key_name: str
    encrypted_value: str
    updated_at: float


class CredentialProvider:
    def get_wix_api_token(self) -> str | None:
        raise NotImplementedError


class EnvironmentCredentialProvider(CredentialProvider):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def get_wix_api_token(self) -> str | None:
        token = self._settings.wix_api_token.strip() or None
        logger.debug(
            "credentials.provider.env.loaded",
            extra={
                "provider": "env",
                "token_preview": redact_secret(token),
            },
        )
        return token


class EncryptedDatabaseCredentialProvider(CredentialProvider):
    """Scaffold provider for encrypted DB credential storage.

    This provider stores encrypted credential values in SQLite and decrypts them
    only in-memory when requested.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._db_file = Path(settings.credential_db_path)
        self._db_file.parent.mkdir(parents=True, exist_ok=True)
        self._key_material = _derive_key_material(settings.credential_encryption_key)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_file) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS secret_credential (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    key_name TEXT NOT NULL,
                    encrypted_value TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(provider, key_name)
                )
                """
            )
            connection.commit()

    def _encrypt(self, plain_text: str) -> str:
        raw = plain_text.encode("utf-8")
        encrypted = _xor_crypt(raw, self._key_material)
        return base64.urlsafe_b64encode(encrypted).decode("ascii")

    def _decrypt(self, encrypted_text: str) -> str:
        raw = base64.urlsafe_b64decode(encrypted_text.encode("ascii"))
        decrypted = _xor_crypt(raw, self._key_material)
        return decrypted.decode("utf-8")

    def set_wix_api_token(self, token: str) -> None:
        encrypted = self._encrypt(token)
        with sqlite3.connect(self._db_file) as connection:
            connection.execute(
                """
                INSERT INTO secret_credential (provider, key_name, encrypted_value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(provider, key_name)
                DO UPDATE SET encrypted_value=excluded.encrypted_value, updated_at=excluded.updated_at
                """,
                ("wix", "api_token", encrypted, time()),
            )
            connection.commit()

    def _fetch_record(self) -> CredentialRecord | None:
        with sqlite3.connect(self._db_file) as connection:
            row = connection.execute(
                """
                SELECT provider, key_name, encrypted_value, updated_at
                FROM secret_credential
                WHERE provider = ? AND key_name = ?
                LIMIT 1
                """,
                ("wix", "api_token"),
            ).fetchone()
        if row is None:
            return None
        return CredentialRecord(
            provider=str(row[0]),
            key_name=str(row[1]),
            encrypted_value=str(row[2]),
            updated_at=float(row[3]),
        )

    def get_wix_api_token(self) -> str | None:
        record = self._fetch_record()
        if record is None:
            logger.debug(
                "credentials.provider.db.missing",
                extra={"provider": "db"},
            )
            return None
        decrypted = self._decrypt(record.encrypted_value)
        logger.debug(
            "credentials.provider.db.loaded",
            extra={
                "provider": "db",
                "token_preview": redact_secret(decrypted),
            },
        )
        return decrypted.strip() or None


def get_credential_provider(settings: Settings) -> CredentialProvider:
    if settings.credential_provider_mode == "db":
        return EncryptedDatabaseCredentialProvider(settings)
    return EnvironmentCredentialProvider(settings)

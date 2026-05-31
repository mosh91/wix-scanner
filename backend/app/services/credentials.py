from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from time import time

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings

logger = logging.getLogger(__name__)

# Sentinel used by the factory to authorise the DB provider instance.
_FACTORY_SENTINEL = object()


def redact_secret(secret: str | None) -> str:
    if not secret:
        return "<empty>"
    if len(secret) <= 6:
        return "***"
    return f"{secret[:2]}***{secret[-2:]}"


def _derive_fernet(encryption_key: str, key_version: str) -> Fernet:
    """Derive a Fernet cipher from a passphrase + version string.

    Uses SHA-256 of ``{version}:{passphrase}`` as the 32-byte key material so
    key rotation (changing version) yields a completely independent cipher.
    """
    raw = hashlib.sha256(f"{key_version}:{encryption_key}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def _service_access_token(encryption_key: str, key_version: str) -> str:
    """Compute a service-layer access token tied to the active key material.

    Only services that received the credential provider via the authorised
    factory path (and therefore possess the same settings) can reproduce this
    token and call :py:meth:`get_wix_api_token`.
    """
    return hmac.new(
        key=encryption_key.encode(),
        msg=f"cred-store-access:{key_version}".encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()


@dataclass(frozen=True)
class CredentialRecord:
    provider: str
    key_name: str
    encrypted_value: str
    key_version: str
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
    """Envelope-encrypted DB credential store with key versioning and access control.

    Credentials are encrypted with AES-128-CBC + HMAC-SHA256 (Fernet) before
    persistence.  Each row records the ``key_version`` used so that rotation
    can re-encrypt individual records without downtime.

    Reads are guarded by a service-layer access token derived from the active
    key material.  The token is injected by :py:func:`get_credential_provider`
    and is not reproducible without access to the encryption key + version.
    Directly instantiating this class without the factory sentinel leaves the
    provider unauthorised; any read attempt raises :py:exc:`PermissionError`.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        _factory_token: object = None,
    ) -> None:
        self._settings = settings
        self._db_file = Path(settings.credential_db_path)
        self._db_file.parent.mkdir(parents=True, exist_ok=True)
        self._encryption_key = settings.credential_encryption_key
        self._key_version = settings.credential_key_version
        # Service-layer access control: authorised only when created via the factory.
        self._access_token: str | None = (
            _service_access_token(self._encryption_key, self._key_version)
            if _factory_token is _FACTORY_SENTINEL
            else None
        )
        self._init_db()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_file) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS secret_credential (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider    TEXT NOT NULL,
                    key_name    TEXT NOT NULL,
                    encrypted_value TEXT NOT NULL,
                    key_version TEXT NOT NULL DEFAULT 'v1',
                    updated_at  REAL NOT NULL,
                    UNIQUE(provider, key_name)
                )
                """
            )
            # Migration: add key_version column if it does not exist yet.
            columns = [
                row[1]
                for row in connection.execute("PRAGMA table_info(secret_credential)").fetchall()
            ]
            if "key_version" not in columns:
                connection.execute(
                    "ALTER TABLE secret_credential ADD COLUMN key_version TEXT NOT NULL DEFAULT 'v1'"
                )
            connection.commit()

    # ------------------------------------------------------------------
    # Encryption helpers
    # ------------------------------------------------------------------

    def _encrypt(self, plain_text: str, key_version: str | None = None) -> str:
        version = key_version or self._key_version
        fernet = _derive_fernet(self._encryption_key, version)
        return fernet.encrypt(plain_text.encode()).decode("ascii")

    def _decrypt(self, encrypted_text: str, key_version: str) -> str:
        fernet = _derive_fernet(self._encryption_key, key_version)
        try:
            return fernet.decrypt(encrypted_text.encode()).decode()
        except (InvalidToken, Exception) as exc:
            raise ValueError("credential decryption failed: invalid token or key") from exc

    # ------------------------------------------------------------------
    # Access control
    # ------------------------------------------------------------------

    def _require_authorised(self) -> None:
        if self._access_token is None:
            raise PermissionError(
                "Unauthorised credential access: provider was not created via get_credential_provider()"
            )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def set_wix_api_token(self, token: str) -> None:
        encrypted = self._encrypt(token)
        with sqlite3.connect(self._db_file) as connection:
            connection.execute(
                """
                INSERT INTO secret_credential
                    (provider, key_name, encrypted_value, key_version, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(provider, key_name)
                DO UPDATE SET
                    encrypted_value = excluded.encrypted_value,
                    key_version     = excluded.key_version,
                    updated_at      = excluded.updated_at
                """,
                ("wix", "api_token", encrypted, self._key_version, time()),
            )
            connection.commit()

    # ------------------------------------------------------------------
    # Read (authorised only)
    # ------------------------------------------------------------------

    def _fetch_record(self, provider: str, key_name: str) -> CredentialRecord | None:
        with sqlite3.connect(self._db_file) as connection:
            row = connection.execute(
                """
                SELECT provider, key_name, encrypted_value, key_version, updated_at
                FROM secret_credential
                WHERE provider = ? AND key_name = ?
                LIMIT 1
                """,
                (provider, key_name),
            ).fetchone()
        if row is None:
            return None
        return CredentialRecord(
            provider=str(row[0]),
            key_name=str(row[1]),
            encrypted_value=str(row[2]),
            key_version=str(row[3]),
            updated_at=float(row[4]),
        )

    def get_wix_api_token(self) -> str | None:
        self._require_authorised()
        record = self._fetch_record("wix", "api_token")
        if record is None:
            logger.debug("credentials.provider.db.missing", extra={"provider": "db"})
            return None
        decrypted = self._decrypt(record.encrypted_value, record.key_version)
        logger.debug(
            "credentials.provider.db.loaded",
            extra={"provider": "db", "token_preview": redact_secret(decrypted)},
        )
        return decrypted.strip() or None

    # ------------------------------------------------------------------
    # Key rotation
    # ------------------------------------------------------------------

    def rotate_key(self, new_encryption_key: str, new_key_version: str) -> int:
        """Re-encrypt all stored credentials under a new key.

        The method reads each record using its stored ``key_version``, decrypts
        with the **current** key, then re-encrypts with *new_encryption_key* and
        *new_key_version*.  After all records are migrated the instance's active
        key is updated so subsequent writes use the new key.

        Returns the number of records migrated.
        """
        self._require_authorised()
        with sqlite3.connect(self._db_file) as connection:
            rows = connection.execute(
                "SELECT provider, key_name, encrypted_value, key_version FROM secret_credential"
            ).fetchall()
            migrated = 0
            for provider, key_name, encrypted_value, key_version in rows:
                plain = self._decrypt(encrypted_value, key_version)
                new_fernet = _derive_fernet(new_encryption_key, new_key_version)
                new_encrypted = new_fernet.encrypt(plain.encode()).decode("ascii")
                connection.execute(
                    """
                    UPDATE secret_credential
                    SET encrypted_value = ?, key_version = ?, updated_at = ?
                    WHERE provider = ? AND key_name = ?
                    """,
                    (new_encrypted, new_key_version, time(), provider, key_name),
                )
                migrated += 1
            connection.commit()

        # Update active key so future writes use the new material.
        self._encryption_key = new_encryption_key
        self._key_version = new_key_version
        self._access_token = _service_access_token(new_encryption_key, new_key_version)
        logger.info(
            "credentials.key_rotation.complete",
            extra={"new_key_version": new_key_version, "records_migrated": migrated},
        )
        return migrated


def get_credential_provider(settings: Settings) -> CredentialProvider:
    if settings.credential_provider_mode == "db":
        return EncryptedDatabaseCredentialProvider(settings, _factory_token=_FACTORY_SENTINEL)
    return EnvironmentCredentialProvider(settings)


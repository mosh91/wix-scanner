"""Relay registry and bootstrap credential service for P2-US-09.

Tracks venue relay instances (health, queue depth, credentials) and manages
signed one-time / reusable bootstrap tokens that kiosks scan to activate
the correct event+station scope.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import Column, String, Integer, DateTime, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import Settings, get_settings


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------

class _Base(DeclarativeBase):
    pass


class _RelayInstanceRow(_Base):
    __tablename__ = "relay_instance"

    relay_id = Column(String, primary_key=True)
    relay_name = Column(String, nullable=False)
    venue = Column(String, nullable=False)
    station_id = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active")
    last_heartbeat = Column(DateTime(timezone=True), nullable=True)
    software_version = Column(String, nullable=True)
    queue_depth = Column(Integer, nullable=False, default=0)
    # Stored as hex-encoded HMAC-SHA256 of the token
    auth_token_hash = Column(String, nullable=True)
    auth_token_preview = Column(String, nullable=True)
    credentials_rotated_at = Column(DateTime(timezone=True), nullable=True)
    # Grace window: old credentials remain valid until this timestamp
    grace_expires_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class _BootstrapCredentialRow(_Base):
    __tablename__ = "bootstrap_credentials"

    credential_id = Column(String, primary_key=True)
    relay_id = Column(String, nullable=True)
    station_id = Column(String, nullable=False)
    event_id = Column(String, nullable=False)
    door_id = Column(String, nullable=True)
    # HMAC-signed token payload stored; the signed token is returned to caller on creation
    token_hash = Column(String, nullable=False)
    token_preview = Column(String, nullable=False)  # last-8 chars for display
    mode = Column(String, nullable=False)  # "one_time" | "reusable_with_expiry"
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_by = Column(String, nullable=True)
    used_at = Column(DateTime(timezone=True), nullable=True)
    used_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    created_by_actor = Column(String, nullable=False)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

RelayStatus = Literal["active", "disabled"]
BootstrapMode = Literal["one_time", "reusable_with_expiry"]

HEARTBEAT_STALE_MINUTES = 5  # after this interval, relay is considered degraded


@dataclass(frozen=True)
class RelayInstanceRecord:
    relay_id: str
    relay_name: str
    venue: str
    station_id: str
    status: RelayStatus
    last_heartbeat: str | None
    software_version: str | None
    queue_depth: int
    auth_token_preview: str | None
    credentials_rotated_at: str | None
    grace_expires_at: str | None
    notes: str | None
    created_at: str
    # Derived
    heartbeat_stale: bool


@dataclass(frozen=True)
class BootstrapCredentialRecord:
    credential_id: str
    relay_id: str | None
    station_id: str
    event_id: str
    door_id: str | None
    token_preview: str
    mode: BootstrapMode
    expires_at: str
    revoked_at: str | None
    revoked_by: str | None
    used_at: str | None
    used_by: str | None
    created_at: str
    created_by_actor: str


@dataclass(frozen=True)
class GeneratedBootstrapToken:
    """Returned once on creation — token is not stored in plaintext."""
    credential_id: str
    signed_token: str  # format: {credential_id}.{payload_b64}.{sig_hex}
    bootstrap_url: str  # wix-scanner://bootstrap?token={signed_token}
    expires_at: str
    mode: BootstrapMode


@dataclass(frozen=True)
class RotatedRelayCredentials:
    relay_id: str
    new_auth_token: str  # returned once; store hash only
    grace_expires_at: str


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

def _fmt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def _row_to_relay(row: _RelayInstanceRow) -> RelayInstanceRecord:
    if row.last_heartbeat is None:
        stale = True
    else:
        age = datetime.now(tz=UTC) - row.last_heartbeat.replace(tzinfo=UTC)
        stale = age > timedelta(minutes=HEARTBEAT_STALE_MINUTES)
    return RelayInstanceRecord(
        relay_id=row.relay_id,
        relay_name=row.relay_name,
        venue=row.venue,
        station_id=row.station_id,
        status=row.status,
        last_heartbeat=_fmt(row.last_heartbeat),
        software_version=row.software_version,
        queue_depth=row.queue_depth,
        auth_token_preview=row.auth_token_preview,
        credentials_rotated_at=_fmt(row.credentials_rotated_at),
        grace_expires_at=_fmt(row.grace_expires_at),
        notes=row.notes,
        created_at=_fmt(row.created_at) or "",
        heartbeat_stale=stale,
    )


def _row_to_bootstrap(row: _BootstrapCredentialRow) -> BootstrapCredentialRecord:
    return BootstrapCredentialRecord(
        credential_id=row.credential_id,
        relay_id=row.relay_id,
        station_id=row.station_id,
        event_id=row.event_id,
        door_id=row.door_id,
        token_preview=row.token_preview,
        mode=row.mode,
        expires_at=_fmt(row.expires_at) or "",
        revoked_at=_fmt(row.revoked_at),
        revoked_by=row.revoked_by,
        used_at=_fmt(row.used_at),
        used_by=row.used_by,
        created_at=_fmt(row.created_at) or "",
        created_by_actor=row.created_by_actor,
    )


def _sign_token(secret: str, credential_id: str, payload: str) -> str:
    """Return HMAC-SHA256 hex of '{credential_id}:{payload}'."""
    msg = f"{credential_id}:{payload}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def _build_signed_token(secret: str, credential_id: str, event_id: str,
                        station_id: str, expires_at: str) -> str:
    """Build a signed token string the kiosk can carry."""
    payload = json.dumps(
        {"c": credential_id, "e": event_id, "s": station_id, "x": expires_at},
        separators=(",", ":"),
    )
    import base64
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = _sign_token(secret, credential_id, payload_b64)
    return f"{credential_id}.{payload_b64}.{sig}"


class RelayRegistryService:
    def __init__(self, *, settings: Settings | None = None, db_path: str | None = None) -> None:
        self._settings = settings or get_settings()
        db_url = (
            f"sqlite:///{db_path}"
            if db_path
            else f"sqlite:///{self._settings.relay_registry_db_path}"
        )
        engine = create_engine(db_url, connect_args={"check_same_thread": False})
        _Base.metadata.create_all(engine)
        self._Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    # ------------------------------------------------------------------
    # Relay instances
    # ------------------------------------------------------------------

    def register_relay(
        self,
        *,
        relay_name: str,
        venue: str,
        station_id: str,
        notes: str | None = None,
    ) -> tuple[RelayInstanceRecord, str]:
        """Register a new relay. Returns (record, raw_auth_token)."""
        relay_id = str(uuid.uuid4())
        raw_token = secrets.token_urlsafe(32)
        token_hash = hmac.new(
            self._settings.bootstrap_secret.encode(), raw_token.encode(), hashlib.sha256
        ).hexdigest()
        now = datetime.now(tz=UTC)
        row = _RelayInstanceRow(
            relay_id=relay_id,
            relay_name=relay_name,
            venue=venue,
            station_id=station_id,
            status="active",
            last_heartbeat=None,
            software_version=None,
            queue_depth=0,
            auth_token_hash=token_hash,
            auth_token_preview=raw_token[-4:],
            credentials_rotated_at=None,
            grace_expires_at=None,
            notes=notes,
            created_at=now,
        )
        with self._Session() as session:
            session.add(row)
            session.commit()
        return _row_to_relay(row), raw_token

    def list_relays(self) -> list[RelayInstanceRecord]:
        with self._Session() as session:
            rows = session.query(_RelayInstanceRow).order_by(_RelayInstanceRow.relay_name).all()
        return [_row_to_relay(r) for r in rows]

    def get_relay(self, relay_id: str) -> RelayInstanceRecord | None:
        with self._Session() as session:
            row = session.query(_RelayInstanceRow).filter_by(relay_id=relay_id).first()
        return _row_to_relay(row) if row else None

    def update_heartbeat(
        self,
        relay_id: str,
        *,
        queue_depth: int = 0,
        software_version: str | None = None,
    ) -> RelayInstanceRecord:
        now = datetime.now(tz=UTC)
        with self._Session() as session:
            row = session.query(_RelayInstanceRow).filter_by(relay_id=relay_id).first()
            if row is None:
                raise KeyError(relay_id)
            row.last_heartbeat = now
            row.queue_depth = queue_depth
            if software_version is not None:
                row.software_version = software_version
            session.commit()
            return _row_to_relay(row)

    def set_relay_status(self, relay_id: str, *, status: RelayStatus) -> RelayInstanceRecord:
        with self._Session() as session:
            row = session.query(_RelayInstanceRow).filter_by(relay_id=relay_id).first()
            if row is None:
                raise KeyError(relay_id)
            row.status = status
            session.commit()
            return _row_to_relay(row)

    def rotate_relay_credentials(
        self, relay_id: str, *, grace_minutes: int = 15
    ) -> tuple[RelayInstanceRecord, str]:
        """Issue new credentials with a grace window. Returns (record, new_raw_token)."""
        raw_token = secrets.token_urlsafe(32)
        token_hash = hmac.new(
            self._settings.bootstrap_secret.encode(), raw_token.encode(), hashlib.sha256
        ).hexdigest()
        now = datetime.now(tz=UTC)
        grace_dt = now + timedelta(minutes=grace_minutes)
        with self._Session() as session:
            row = session.query(_RelayInstanceRow).filter_by(relay_id=relay_id).first()
            if row is None:
                raise KeyError(relay_id)
            row.auth_token_hash = token_hash
            row.auth_token_preview = raw_token[-4:]
            row.credentials_rotated_at = now
            row.grace_expires_at = grace_dt
            session.commit()
            return _row_to_relay(row), raw_token

    # ------------------------------------------------------------------
    # Bootstrap credentials
    # ------------------------------------------------------------------

    def create_bootstrap_credential(
        self,
        *,
        event_id: str,
        station_id: str,
        actor: str,
        mode: BootstrapMode = "one_time",
        expires_minutes: int = 60,
        relay_id: str | None = None,
        door_id: str | None = None,
    ) -> tuple[BootstrapCredentialRecord, GeneratedBootstrapToken]:
        credential_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC)
        expires_at = now + timedelta(minutes=expires_minutes)
        expires_str = expires_at.isoformat().replace("+00:00", "Z")
        signed = _build_signed_token(
            self._settings.bootstrap_secret,
            credential_id,
            event_id,
            station_id,
            expires_str,
        )
        token_hash = hmac.new(
            self._settings.bootstrap_secret.encode(),
            signed.encode(),
            hashlib.sha256,
        ).hexdigest()
        row = _BootstrapCredentialRow(
            credential_id=credential_id,
            relay_id=relay_id,
            station_id=station_id,
            event_id=event_id,
            door_id=door_id,
            token_hash=token_hash,
            token_preview=signed[-8:],
            mode=mode,
            expires_at=expires_at,
            revoked_at=None,
            revoked_by=None,
            used_at=None,
            used_by=None,
            created_at=now,
            created_by_actor=actor,
        )
        with self._Session() as session:
            session.add(row)
            session.commit()
        rec = _row_to_bootstrap(row)
        generated = GeneratedBootstrapToken(
            credential_id=credential_id,
            signed_token=signed,
            bootstrap_url=f"wix-scanner://bootstrap?token={signed}",
            expires_at=expires_str,
            mode=mode,
        )
        return rec, generated

    def list_bootstrap_credentials(
        self, *, event_id: str | None = None, include_expired: bool = False
    ) -> list[BootstrapCredentialRecord]:
        now = datetime.now(tz=UTC)
        with self._Session() as session:
            q = session.query(_BootstrapCredentialRow)
            if event_id:
                q = q.filter(_BootstrapCredentialRow.event_id == event_id)
            if not include_expired:
                q = q.filter(_BootstrapCredentialRow.expires_at >= now)
            rows = q.order_by(_BootstrapCredentialRow.created_at.desc()).all()
        return [_row_to_bootstrap(r) for r in rows]

    def revoke_bootstrap_credential(
        self, credential_id: str, *, actor: str
    ) -> BootstrapCredentialRecord:
        now = datetime.now(tz=UTC)
        with self._Session() as session:
            row = session.query(_BootstrapCredentialRow).filter_by(
                credential_id=credential_id
            ).first()
            if row is None:
                raise KeyError(credential_id)
            if row.revoked_at is not None:
                raise ValueError("already revoked")
            row.revoked_at = now
            row.revoked_by = actor
            session.commit()
            return _row_to_bootstrap(row)

    def validate_bootstrap_token(
        self, signed_token: str, *, actor: str | None = None
    ) -> dict[str, object]:
        """
        Validate a signed bootstrap token.  Returns a dict with keys:
          valid, credential_id, event_id, station_id, expires_at, reason (on failure).
        On success marks one_time tokens as used.
        """
        import base64

        parts = signed_token.split(".")
        if len(parts) != 3:
            return {"valid": False, "reason": "malformed_token"}
        credential_id, payload_b64, provided_sig = parts

        # Re-derive expected sig
        expected_sig = _sign_token(
            self._settings.bootstrap_secret, credential_id, payload_b64
        )
        if not hmac.compare_digest(expected_sig, provided_sig):
            return {"valid": False, "reason": "invalid_signature"}

        # Decode payload
        try:
            padding = "=" * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
        except Exception:
            return {"valid": False, "reason": "malformed_payload"}

        expires_at_str = payload.get("x", "")
        try:
            expires_dt = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        except ValueError:
            return {"valid": False, "reason": "invalid_expiry"}

        if datetime.now(tz=UTC) > expires_dt:
            return {"valid": False, "reason": "expired"}

        # Lookup in DB
        with self._Session() as session:
            row = session.query(_BootstrapCredentialRow).filter_by(
                credential_id=credential_id
            ).first()
            if row is None:
                return {"valid": False, "reason": "credential_not_found"}
            if row.revoked_at is not None:
                return {"valid": False, "reason": "revoked"}
            if row.mode == "one_time" and row.used_at is not None:
                return {"valid": False, "reason": "already_used"}
            # Mark used if one_time
            if row.mode == "one_time":
                row.used_at = datetime.now(tz=UTC)
                row.used_by = actor or "unknown"
                session.commit()

        return {
            "valid": True,
            "credential_id": credential_id,
            "event_id": payload.get("e"),
            "station_id": payload.get("s"),
            "expires_at": expires_at_str,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_service_instance: RelayRegistryService | None = None


def get_relay_registry_service(settings: Settings | None = None) -> RelayRegistryService:
    global _service_instance  # noqa: PLW0603
    if _service_instance is None:
        s = settings or get_settings()
        _service_instance = RelayRegistryService(settings=s)
    return _service_instance


def set_relay_registry_service(service: RelayRegistryService | None) -> None:
    """Override the singleton — used in tests to inject a fresh isolated service."""
    global _service_instance  # noqa: PLW0603
    _service_instance = service

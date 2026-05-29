"""
Bootstrap QR validation and kiosk session enrollment.

QR payload format:
  Normal:  BOOTSTRAP:v1:{event_id}:{station_id}:{expires_at_unix}:{hmac_sha256_hex}
  Admin:   ADMIN_BOOTSTRAP:v1:{event_id}:{station_id}:{expires_at_unix}:{hmac_sha256_hex}

HMAC message = "v1:{event_id}:{station_id}:{expires_at_unix}"
"""

from __future__ import annotations

import hashlib
import hmac as hmac_lib
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings

router = APIRouter(prefix="/bootstrap")

BOOTSTRAP_PREFIX = "BOOTSTRAP:v1:"
ADMIN_BOOTSTRAP_PREFIX = "ADMIN_BOOTSTRAP:v1:"

# In-memory store of active bootstrap sessions  {session_id -> _BootstrapSession}
_active_sessions: dict[str, _BootstrapSession] = {}


class _BootstrapSession:
    __slots__ = ("session_id", "event_id", "station_id", "expires_at", "is_admin")

    def __init__(
        self,
        session_id: str,
        event_id: str,
        station_id: str,
        expires_at: int,
        is_admin: bool = False,
    ) -> None:
        self.session_id = session_id
        self.event_id = event_id
        self.station_id = station_id
        self.expires_at = expires_at
        self.is_admin = is_admin


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class BootstrapValidateRequest(BaseModel):
    payload: str = Field(min_length=10, max_length=1024)
    # Current enrolled event, if any — used to detect cross-event switch attempts
    current_event_id: str | None = Field(default=None)


class BootstrapSessionResponse(BaseModel):
    bootstrap_session_id: str
    event_id: str
    station_id: str
    expires_at: int
    is_admin_override: bool


class BootstrapClearRequest(BaseModel):
    bootstrap_session_id: str


class BootstrapGenerateResponse(BaseModel):
    qr_payload: str
    event_id: str
    station_id: str
    expires_at: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sign(event_id: str, station_id: str, expires_at: int, secret: str) -> str:
    message = f"v1:{event_id}:{station_id}:{expires_at}"
    return hmac_lib.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def _verify_token(
    payload: str, secret: str
) -> tuple[str, str, int, bool] | None:
    """
    Returns (event_id, station_id, expires_at, is_admin) or None if invalid/expired.
    """
    is_admin = False
    if payload.startswith(ADMIN_BOOTSTRAP_PREFIX):
        is_admin = True
        normalized = payload[len(ADMIN_BOOTSTRAP_PREFIX):]
    elif payload.startswith(BOOTSTRAP_PREFIX):
        normalized = payload[len(BOOTSTRAP_PREFIX):]
    else:
        return None

    # normalized = "{event_id}:{station_id}:{expires_at}:{hmac_hex}"
    parts = normalized.split(":", 3)
    if len(parts) != 4:
        return None

    event_id, station_id, expires_at_str, provided_hmac = parts

    try:
        expires_at = int(expires_at_str)
    except ValueError:
        return None

    if expires_at < int(time.time()):
        return None

    expected_hmac = _sign(event_id, station_id, expires_at, secret)
    if not hmac_lib.compare_digest(provided_hmac, expected_hmac):
        return None

    return event_id, station_id, expires_at, is_admin


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/validate",
    response_model=BootstrapSessionResponse,
    status_code=status.HTTP_200_OK,
    summary="Validate bootstrap QR and create kiosk session",
)
def validate_bootstrap(
    request: BootstrapValidateRequest,
    settings: Settings = Depends(get_settings),
) -> BootstrapSessionResponse:
    """
    Validates a bootstrap QR payload and creates a kiosk session binding.

    - If `current_event_id` is set and the QR targets a *different* event,
      the kiosk must use an `ADMIN_BOOTSTRAP` QR to force the switch.
    - Returns the new session context (event, station, expiry).
    """
    result = _verify_token(request.payload, settings.bootstrap_secret)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="QR de arranque inválido o expirado.",
        )

    event_id, station_id, expires_at, is_admin = result

    # Guard: switching events requires admin override QR
    if (
        request.current_event_id is not None
        and request.current_event_id != event_id
        and not is_admin
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "El kiosco ya está activo para otro evento. "
                "Use el QR de administrador para cambiar."
            ),
        )

    session_id = str(uuid.uuid4())
    _active_sessions[session_id] = _BootstrapSession(
        session_id=session_id,
        event_id=event_id,
        station_id=station_id,
        expires_at=expires_at,
        is_admin=is_admin,
    )

    return BootstrapSessionResponse(
        bootstrap_session_id=session_id,
        event_id=event_id,
        station_id=station_id,
        expires_at=expires_at,
        is_admin_override=is_admin,
    )


@router.post(
    "/clear",
    summary="Clear (sign out) a kiosk bootstrap session",
)
def clear_bootstrap_session(request: BootstrapClearRequest) -> Response:
    """Explicitly clears a bootstrap session on reset or sign-out."""
    _active_sessions.pop(request.bootstrap_session_id, None)
    return Response(status_code=204)


@router.get(
    "/generate",
    response_model=BootstrapGenerateResponse,
    summary="[DEV] Generate a valid bootstrap QR payload for testing",
)
def generate_bootstrap_qr(
    event_id: str,
    station_id: str,
    ttl_seconds: int = 43200,
    is_admin: bool = False,
    settings: Settings = Depends(get_settings),
) -> BootstrapGenerateResponse:
    """
    **Development / staging only.**  Generates a valid signed bootstrap QR payload.
    Blocked in production environments.
    """
    if settings.environment == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bootstrap QR generation is not available in production.",
        )

    expires_at = int(time.time()) + max(60, min(ttl_seconds, 86400))
    signature = _sign(event_id, station_id, expires_at, settings.bootstrap_secret)
    prefix = ADMIN_BOOTSTRAP_PREFIX if is_admin else BOOTSTRAP_PREFIX
    qr_payload = f"{prefix}{event_id}:{station_id}:{expires_at}:{signature}"

    return BootstrapGenerateResponse(
        qr_payload=qr_payload,
        event_id=event_id,
        station_id=station_id,
        expires_at=expires_at,
    )

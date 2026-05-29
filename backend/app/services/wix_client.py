from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Final

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_RETRYABLE_HTTP_STATUSES: Final[set[int]] = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class WixCheckinResult:
    outcome: str
    wix_status: str
    reason: str | None
    error_code: str
    attempts: int
    http_status: int | None = None


class WixClient:
    """Thin Wix check-in API client with retry and jitter handling."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def check_in_ticket(
        self,
        *,
        event_id: str,
        ticket_number: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> WixCheckinResult:
        if self._settings.wix_mock_mode:
            return self._mock_checkin(ticket_number=ticket_number)

        if not self._settings.wix_api_token:
            return WixCheckinResult(
                outcome="auth_error",
                wix_status="auth_error",
                reason="Wix API token no configurado.",
                error_code="WIX_AUTH_NOT_CONFIGURED",
                attempts=0,
            )

        url = f"{self._settings.wix_base_url.rstrip('/')}{self._settings.wix_checkin_path}"
        max_attempts = max(1, self._settings.wix_max_retries + 1)

        payload = {
            "eventId": event_id,
            "ticketNumber": [ticket_number],
        }
        headers = {
            "Authorization": f"Bearer {self._settings.wix_api_token}",
            "Content-Type": "application/json",
            "X-Idempotency-Key": idempotency_key,
            "X-Correlation-ID": correlation_id,
        }

        for attempt in range(1, max_attempts + 1):
            try:
                with httpx.Client(timeout=self._settings.wix_timeout_ms / 1000.0) as client:
                    response = client.post(url, json=payload, headers=headers)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                logger.warning(
                    "wix.checkin.request_failed",
                    extra={
                        "correlation_id": correlation_id,
                        "attempt": attempt,
                        "error": type(exc).__name__,
                    },
                )
                if attempt < max_attempts:
                    self._sleep_with_backoff(attempt)
                    continue
                return WixCheckinResult(
                    outcome="transient_error",
                    wix_status="unavailable",
                    reason="Wix no responde temporalmente.",
                    error_code="WIX_TIMEOUT",
                    attempts=attempt,
                )

            mapped = self._map_response(response, attempt)
            if mapped.outcome in {"checked_in", "already_checked_in", "invalid_ticket", "auth_error"}:
                return mapped

            if attempt < max_attempts and response.status_code in _RETRYABLE_HTTP_STATUSES:
                self._sleep_with_backoff(attempt)
                continue
            return mapped

        return WixCheckinResult(
            outcome="transient_error",
            wix_status="unavailable",
            reason="Fallo inesperado al contactar Wix.",
            error_code="WIX_UNKNOWN_ERROR",
            attempts=max_attempts,
        )

    def _map_response(self, response: httpx.Response, attempt: int) -> WixCheckinResult:
        if response.status_code in {200, 201}:
            return WixCheckinResult(
                outcome="checked_in",
                wix_status="checked_in",
                reason=None,
                error_code="",
                attempts=attempt,
                http_status=response.status_code,
            )
        if response.status_code == 409:
            return WixCheckinResult(
                outcome="already_checked_in",
                wix_status="duplicate",
                reason="Ticket ya registrado en Wix.",
                error_code="ALREADY_CHECKED_IN",
                attempts=attempt,
                http_status=response.status_code,
            )
        if response.status_code in {400, 404, 422}:
            return WixCheckinResult(
                outcome="invalid_ticket",
                wix_status="rejected",
                reason="Wix rechazó el ticket por formato o contexto.",
                error_code="INVALID_TICKET",
                attempts=attempt,
                http_status=response.status_code,
            )
        if response.status_code in {401, 403}:
            return WixCheckinResult(
                outcome="auth_error",
                wix_status="auth_error",
                reason="Wix rechazó las credenciales de integración.",
                error_code="WIX_AUTH_ERROR",
                attempts=attempt,
                http_status=response.status_code,
            )
        if response.status_code == 429:
            return WixCheckinResult(
                outcome="rate_limited",
                wix_status="rate_limited",
                reason="Wix devolvió rate-limit.",
                error_code="WIX_RATE_LIMITED",
                attempts=attempt,
                http_status=response.status_code,
            )
        if response.status_code >= 500:
            return WixCheckinResult(
                outcome="upstream_error",
                wix_status="upstream_error",
                reason="Wix devolvió error interno.",
                error_code="WIX_5XX",
                attempts=attempt,
                http_status=response.status_code,
            )
        return WixCheckinResult(
            outcome="upstream_error",
            wix_status="upstream_error",
            reason=f"Wix devolvió estado no manejado: {response.status_code}",
            error_code="WIX_UNHANDLED_STATUS",
            attempts=attempt,
            http_status=response.status_code,
        )

    def _sleep_with_backoff(self, attempt: int) -> None:
        base = self._settings.wix_retry_base_ms / 1000.0
        max_backoff = self._settings.wix_retry_max_ms / 1000.0
        backoff = min(base * (2 ** (attempt - 1)), max_backoff)
        jitter = random.uniform(0.0, backoff * 0.25)
        time.sleep(backoff + jitter)

    def _mock_checkin(self, *, ticket_number: str) -> WixCheckinResult:
        token = ticket_number.upper()
        if "DUP" in token or "ALREADY" in token:
            return WixCheckinResult(
                outcome="already_checked_in",
                wix_status="duplicate",
                reason="Ticket ya registrado en Wix.",
                error_code="ALREADY_CHECKED_IN",
                attempts=1,
                http_status=409,
            )
        if "RATE" in token:
            return WixCheckinResult(
                outcome="rate_limited",
                wix_status="rate_limited",
                reason="Wix devolvió rate-limit.",
                error_code="WIX_RATE_LIMITED",
                attempts=1,
                http_status=429,
            )
        if "WIX5XX" in token:
            return WixCheckinResult(
                outcome="upstream_error",
                wix_status="upstream_error",
                reason="Wix devolvió error interno.",
                error_code="WIX_5XX",
                attempts=1,
                http_status=500,
            )
        return WixCheckinResult(
            outcome="checked_in",
            wix_status="checked_in",
            reason=None,
            error_code="",
            attempts=1,
            http_status=201,
        )


def get_wix_client() -> WixClient:
    return WixClient(get_settings())

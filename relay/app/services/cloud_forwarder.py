from __future__ import annotations

import logging

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class CloudForwarder:
    """Service to forward scans from local relay to cloud backend."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def forward_scan(
        self,
        *,
        event_id: str,
        ticket_number: str,
        relay_id: str,
        payload: str,
        correlation_id: str,
        scan_event_id: str | None = None,
    ) -> dict[str, object]:
        """Forward a scan to the cloud backend and return acknowledgement."""
        if not self._settings.cloud_base_url.strip():
            logger.warning("cloud.forwarder.not_configured")
            return {
                "acknowledged": True,
                "outcome": "relay_only",
                "message": "Cloud backend not configured. Scan queued locally.",
            }

        url = f"{self._settings.cloud_base_url.rstrip('/')}/checkins/scan"
        headers = {
            "Authorization": f"Bearer {self._settings.relay_auth_token}",
            "Content-Type": "application/json",
            "X-Relay-ID": relay_id,
            "X-Correlation-ID": correlation_id,
        }

        body = {"payload": payload}
        if scan_event_id:
            body["scan_event_id"] = scan_event_id

        try:
            with httpx.Client(timeout=self._settings.cloud_request_timeout_ms / 1000.0) as client:
                response = client.post(
                    url,
                    headers=headers,
                    json=body,
                )

            if response.status_code >= 200 and response.status_code < 300:
                logger.info(
                    "cloud.forwarder.success",
                    extra={
                        "relay_id": relay_id,
                        "event_id": event_id,
                        "status": response.status_code,
                    },
                )
                return {
                    "acknowledged": True,
                    "outcome": "forwarded",
                    "message": "Scan forwarded to cloud backend.",
                }

            logger.warning(
                "cloud.forwarder.non_2xx",
                extra={
                    "relay_id": relay_id,
                    "status": response.status_code,
                },
            )
            return {
                "acknowledged": True,
                "outcome": "relay_queued",
                "message": "Cloud backend returned non-2xx. Scan stored locally.",
                "cloud_status": response.status_code,
            }
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            logger.warning(
                "cloud.forwarder.connection_failed",
                extra={
                    "relay_id": relay_id,
                    "error": type(exc).__name__,
                },
            )
            return {
                "acknowledged": True,
                "outcome": "relay_queued",
                "message": "Cloud backend unreachable. Scan stored locally for later retry.",
            }

    def get_cloud_health(self) -> dict[str, object]:
        """Check health of cloud backend."""
        if not self._settings.cloud_base_url.strip():
            return {"cloud_reachable": False, "reason": "not_configured"}

        url = f"{self._settings.cloud_base_url.rstrip('/')}/health"
        try:
            with httpx.Client(timeout=2.0) as client:
                response = client.get(url)
            if response.status_code == 200:
                return {"cloud_reachable": True, "status_code": 200}
            return {"cloud_reachable": False, "status_code": response.status_code}
        except (httpx.TimeoutException, httpx.ConnectError):
            return {"cloud_reachable": False, "reason": "connection_failed"}


def get_cloud_forwarder() -> CloudForwarder:
    return CloudForwarder(get_settings())

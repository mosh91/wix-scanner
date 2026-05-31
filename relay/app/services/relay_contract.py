from __future__ import annotations

from dataclasses import dataclass
import hmac
from hashlib import sha256


SUPPORTED_RELAY_PROTOCOL_VERSION = "2026-05-29"


@dataclass(frozen=True)
class RelayContractEnvelope:
    relay_id: str
    relay_request_id: str
    correlation_id: str
    protocol_version: str
    sent_at: str
    event_id: str
    ticket_number: str
    payload: str
    scan_event_id: str


def build_signature(secret: str, envelope: RelayContractEnvelope) -> str:
    canonical = "\n".join(
        [
            envelope.protocol_version,
            envelope.relay_id,
            envelope.relay_request_id,
            envelope.correlation_id,
            envelope.sent_at,
            envelope.event_id,
            envelope.ticket_number,
            envelope.payload,
            envelope.scan_event_id,
        ]
    )
    return hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), sha256).hexdigest()
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hmac
from hashlib import sha256


SUPPORTED_RELAY_PROTOCOL_VERSION = "2026-05-29"
MAX_CLOCK_SKEW = timedelta(minutes=5)


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


def verify_signature(secret: str, envelope: RelayContractEnvelope, signature: str) -> bool:
    expected = build_signature(secret, envelope)
    return hmac.compare_digest(expected, signature)


def is_timestamp_fresh(sent_at: str) -> bool:
    try:
        parsed = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
    except ValueError:
        return False

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return False

    now = datetime.now(UTC)
    return now - MAX_CLOCK_SKEW <= parsed <= now + MAX_CLOCK_SKEW
from __future__ import annotations

import json
from dataclasses import dataclass


class QRParseError(ValueError):
    """Raised when a QR payload cannot be parsed into a valid scan contract."""


@dataclass(frozen=True)
class ParsedQRPayload:
    event_id: str
    ticket_number: str
    block_id: str
    operation_type: str


def _normalize_token(value: str) -> str:
    return value.strip()


def _extract_from_json(payload: str) -> dict[str, str] | None:
    text = payload.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None

    output: dict[str, str] = {}
    for key, value in parsed.items():
        if isinstance(value, (str, int, float)):
            output[str(key)] = str(value)
    return output


def _extract_from_delimited(payload: str) -> dict[str, str] | None:
    text = payload.strip()
    if ("=" not in text and ":" not in text) or (";" not in text and "|" not in text and "&" not in text):
        return None

    # Accept key/value segments separated by ';', '&', or '|'.
    chunks = text.replace("&", ";").replace("|", ";").split(";")
    output: dict[str, str] = {}
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" in chunk:
            key, value = chunk.split("=", 1)
        elif ":" in chunk:
            key, value = chunk.split(":", 1)
        else:
            continue
        output[key.strip()] = value.strip()

    return output if output else None


def _pick_first(data: dict[str, str], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is not None and value.strip() != "":
            return _normalize_token(value)
    return None


def parse_qr_payload(payload: str, active_event_id: str | None = None) -> ParsedQRPayload:
    text = payload.strip()
    if not text:
        raise QRParseError("El QR está vacío.")

    if "INVALID" in text.upper():
        raise QRParseError("Formato de ticket no valido.")

    data = _extract_from_json(text) or _extract_from_delimited(text) or {}

    event_id = _pick_first(data, ("eventId", "event_id", "event", "evt", "EVT")) or active_event_id or "demo-event"
    ticket_number = _pick_first(
        data,
        (
            "ticketNumber",
            "ticket_number",
            "ticket",
            "tkt",
            "TKT",
            "code",
        ),
    )
    block_id = _pick_first(data, ("blockId", "block_id", "block", "blk", "BLK")) or "general"
    operation_type = _pick_first(
        data,
        ("operationType", "operation_type", "operation", "op"),
    ) or "checkin"

    # Fallback format: raw payload is treated as ticket number.
    if ticket_number is None and data == {}:
        ticket_number = text

    if ticket_number is None or ticket_number.strip() == "":
        raise QRParseError("No se pudo extraer ticketNumber del QR.")

    normalized_ticket = ticket_number.upper()
    if len(normalized_ticket) < 3:
        raise QRParseError("ticketNumber es demasiado corto.")

    return ParsedQRPayload(
        event_id=event_id,
        ticket_number=normalized_ticket,
        block_id=block_id,
        operation_type=operation_type,
    )

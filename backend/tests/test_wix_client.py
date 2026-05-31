from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.services.wix_client import WixClient


def _settings(**overrides: Any) -> Settings:
    base = Settings(
        wix_mock_mode=False,
        wix_api_token="token-test",
        wix_base_url="https://example.wix.test",
        wix_checkin_path="/events/v1/tickets/check-in",
        wix_max_retries=2,
        wix_retry_base_ms=1,
        wix_retry_max_ms=2,
        wix_timeout_ms=200,
    )
    data = base.model_dump()
    data.update(overrides)
    return Settings(**data)


def test_wix_client_maps_healthy_response_to_checked_in(monkeypatch: Any) -> None:
    client = WixClient(_settings())

    def fake_post(self: httpx.Client, *args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(201, json={"ok": True})

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    result = client.check_in_ticket(
        event_id="evt-1",
        ticket_number="TKT-1",
        idempotency_key="idem-1",
        correlation_id="corr-1",
    )

    assert result.outcome == "checked_in"
    assert result.wix_status == "checked_in"
    assert result.error_code == ""


def test_wix_client_maps_already_checked_in(monkeypatch: Any) -> None:
    client = WixClient(_settings())

    def fake_post(self: httpx.Client, *args: Any, **kwargs: Any) -> httpx.Response:
        return httpx.Response(409)

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    result = client.check_in_ticket(
        event_id="evt-1",
        ticket_number="TKT-DUP",
        idempotency_key="idem-1",
        correlation_id="corr-1",
    )

    assert result.outcome == "already_checked_in"
    assert result.error_code == "ALREADY_CHECKED_IN"


def test_wix_client_retries_rate_limit_and_classifies(monkeypatch: Any) -> None:
    calls = {"count": 0}
    sleeps: list[float] = []
    client = WixClient(_settings(wix_max_retries=2))

    def fake_post(self: httpx.Client, *args: Any, **kwargs: Any) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(429)

    def fake_sleep(value: float) -> None:
        sleeps.append(value)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr("app.services.wix_client.time.sleep", fake_sleep)

    result = client.check_in_ticket(
        event_id="evt-1",
        ticket_number="TKT-RATE",
        idempotency_key="idem-1",
        correlation_id="corr-1",
    )

    assert calls["count"] == 3  # initial + 2 retries
    assert len(sleeps) == 2
    assert result.outcome == "rate_limited"
    assert result.error_code == "WIX_RATE_LIMITED"

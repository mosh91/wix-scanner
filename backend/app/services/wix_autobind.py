from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.services.credentials import get_credential_provider
from app.services.event_block_config import EventBlockConfigService, get_event_block_config_service
from app.services.site_event_binding import SiteEventBindingService, get_site_event_binding_service


@dataclass(frozen=True)
class WixAutobindResult:
    site_id: str
    site_display_name: str | None
    app_instance_id: str
    events_found: int
    events_imported: int
    bindings_created: int
    bindings_verified: int
    existing_bindings: int
    event_ids: list[str]
    binding_ids: list[str]


class WixAutobindService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        event_service: EventBlockConfigService | None = None,
        binding_service: SiteEventBindingService | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._credential_provider = get_credential_provider(self._settings)
        self._event_service = event_service or get_event_block_config_service()
        self._binding_service = binding_service or get_site_event_binding_service()

    @staticmethod
    def _extract_text(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            return text or None
        if isinstance(value, dict):
            for key in ("value", "stringValue", "text", "name", "title"):
                nested = WixAutobindService._extract_text(value.get(key))
                if nested:
                    return nested
            for nested_value in value.values():
                nested = WixAutobindService._extract_text(nested_value)
                if nested:
                    return nested
        return str(value).strip() or None

    def _resolve_app_instance(self) -> tuple[str, str | None, str]:
        if self._settings.wix_mock_mode:
            site_id = "site-demo-01"
            site_display_name = "Demo Site"
            app_instance_id = self._settings.wix_app_instance_id or "mock-instance"
            return site_id, site_display_name, app_instance_id

        token = self._credential_provider.get_wix_api_token()
        if not token:
            raise RuntimeError("Wix API token not configured.")

        url = f"{self._settings.wix_base_url.rstrip('/')}/apps/v1/instance"
        with httpx.Client(timeout=self._settings.wix_timeout_ms / 1000.0) as client:
            response = client.get(url, headers={"Authorization": f"Bearer {token}"})
        if response.status_code >= 400:
            raise RuntimeError(f"Get App Instance failed with HTTP {response.status_code}")

        data = response.json() if response.content else {}
        instance = data.get("instance", {}) if isinstance(data, dict) else {}
        site = data.get("site", {}) if isinstance(data, dict) else {}

        site_id = self._extract_text(site.get("siteId"))
        app_instance_id = self._extract_text(instance.get("instanceId"))
        site_display_name = self._extract_text(site.get("siteDisplayName"))

        if not site_id or not app_instance_id:
            raise RuntimeError("Get App Instance response is missing siteId or instanceId.")

        return site_id, site_display_name, app_instance_id

    def _query_events(self, *, include_drafts: bool = False, page_size: int = 100) -> list[dict[str, Any]]:
        if self._settings.wix_mock_mode:
            events = self._event_service.list_events()
            if not events:
                return [
                    {"id": "event-demo-01", "title": "Demo Event 1"},
                    {"id": "event-demo-02", "title": "Demo Event 2"},
                ]
            return [
                {"id": record.wix_event_id, "title": record.name}
                for record in events
            ]

        token = self._credential_provider.get_wix_api_token()
        if not token:
            raise RuntimeError("Wix API token not configured.")

        url = f"{self._settings.wix_base_url.rstrip('/')}/events/v3/events/query"
        events: list[dict[str, Any]] = []
        offset = 0
        limit = max(1, min(page_size, 100))

        with httpx.Client(timeout=self._settings.wix_timeout_ms / 1000.0) as client:
            while True:
                body: dict[str, Any] = {"query": {"paging": {"limit": limit, "offset": offset}}}
                if include_drafts:
                    body["includeDrafts"] = True
                response = client.post(url, json=body, headers={"Authorization": f"Bearer {token}"})
                if response.status_code >= 400:
                    raise RuntimeError(f"Query Events failed with HTTP {response.status_code}")

                data = response.json() if response.content else {}
                page_events = data.get("events", []) if isinstance(data, dict) else []
                if not isinstance(page_events, list):
                    break

                for item in page_events:
                    if isinstance(item, dict):
                        events.append(item)

                paging_metadata = data.get("pagingMetadata", {}) if isinstance(data, dict) else {}
                total = int(paging_metadata.get("total") or len(events)) if isinstance(paging_metadata, dict) else len(events)
                offset += limit
                if offset >= total or not page_events:
                    break

        return events

    def autobind(self, *, actor: str, include_drafts: bool = False, dry_run: bool = False) -> WixAutobindResult:
        site_id, site_display_name, app_instance_id = self._resolve_app_instance()
        if site_display_name:
            self._binding_service._upsert_wix_site_name(site_id, site_display_name)
        events = self._query_events(include_drafts=include_drafts)

        imported_count = 0
        created_binding_count = 0
        verified_binding_count = 0
        existing_binding_count = 0
        event_ids: list[str] = []
        binding_ids: list[str] = []

        for item in events:
            wix_event_id = self._extract_text(item.get("id"))
            if not wix_event_id:
                continue
            title = self._extract_text(item.get("title")) or self._extract_text(item.get("slug")) or wix_event_id
            self._binding_service._upsert_wix_event_name(wix_event_id, title)
            _, created = self._event_service.upsert_event(
                wix_event_id=wix_event_id,
                name=title,
                timezone="UTC",
                allow_block_overlap=False,
                actor=actor,
            )
            if created:
                imported_count += 1
            event_ids.append(wix_event_id)

            if not dry_run:
                binding = self._binding_service.get_binding_by_event_id(wix_event_id)
                if binding is None:
                    binding = self._binding_service.create_binding(
                        wix_site_id=site_id,
                        wix_event_id=wix_event_id,
                        created_by_actor=actor,
                        verify_immediately=True,
                    )
                    created_binding_count += 1
                else:
                    existing_binding_count += 1
                    binding = self._binding_service.verify_binding(binding_id=binding.binding_id, verified_by_actor=actor)

                if binding.status == "verified":
                    verified_binding_count += 1
                binding_ids.append(binding.binding_id)

        return WixAutobindResult(
            site_id=site_id,
            site_display_name=site_display_name,
            app_instance_id=app_instance_id,
            events_found=len(events),
            events_imported=imported_count,
            bindings_created=created_binding_count,
            bindings_verified=verified_binding_count,
            existing_bindings=existing_binding_count,
            event_ids=event_ids,
            binding_ids=binding_ids,
        )

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.core.config import get_settings
from app.services.credential_lifecycle import CredentialLifecycleRecord, get_credential_lifecycle_service
from app.services.offline_queue import get_offline_queue_service
from app.services.site_event_binding import get_site_event_binding_service
from app.services.ticket_manifest import get_ticket_manifest_service
from app.services.wix_scope_audit import get_wix_scope_audit_service
from app.services.worker_health import get_worker_health_service

ReadinessStatus = Literal["ready", "degraded", "critical"]


@dataclass(frozen=True)
class ReadinessComponentStatus:
    name: str
    status: ReadinessStatus
    message: str
    details: dict[str, object]


@dataclass(frozen=True)
class EventReadinessReport:
    event_id: str
    overall_status: ReadinessStatus
    component_statuses: list[ReadinessComponentStatus]
    failed_checks: list[str]
    recommended_actions: list[str]
    evaluated_at: str
    readiness_acknowledged: bool = False


class EventReadinessService:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._binding_service = get_site_event_binding_service()
        self._credential_service = get_credential_lifecycle_service()
        self._scope_service = get_wix_scope_audit_service()
        self._manifest_service = get_ticket_manifest_service()
        self._offline_queue = get_offline_queue_service()
        self._worker_health = get_worker_health_service()

    def _now(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _component(self, name: str, status: ReadinessStatus, message: str, **details: object) -> ReadinessComponentStatus:
        return ReadinessComponentStatus(name=name, status=status, message=message, details=details)

    def _evaluate_binding(self, event_id: str) -> ReadinessComponentStatus:
        binding = self._binding_service.get_binding_by_event_id(event_id)
        if binding is None:
            return self._component(
                "binding",
                "critical",
                "No verified Wix site-event binding was found for this event.",
                event_id=event_id,
            )
        if binding.status != "verified":
            return self._component(
                "binding",
                "critical",
                "The Wix site-event binding exists but is not verified.",
                binding_id=binding.binding_id,
                binding_status=binding.status,
            )
        return self._component(
            "binding",
            "ready",
            "Verified Wix site-event binding found.",
            binding_id=binding.binding_id,
            wix_site_id=binding.wix_site_id,
            wix_event_id=binding.wix_event_id,
            credential_profile_id=binding.credential_profile_id,
            sync_policy_profile_id=binding.sync_policy_profile_id,
        )

    def _evaluate_credentials(self) -> ReadinessComponentStatus:
        credentials = self._credential_service.list_credentials()
        active_credentials: list[CredentialLifecycleRecord] = []
        expiring_credentials: list[str] = []
        for credential in credentials:
            if credential.lifecycle_state == "active":
                checked = self._credential_service.check_expiry(credential.credential_id, warning_hours=1)
                if checked.lifecycle_state == "expiring_soon":
                    expiring_credentials.append(checked.profile_name)
                else:
                    active_credentials.append(checked)
            elif credential.lifecycle_state == "expiring_soon":
                expiring_credentials.append(credential.profile_name)

        if not active_credentials and not expiring_credentials:
            return self._component(
                "credentials",
                "critical",
                "No active Wix credentials are available.",
                active_count=0,
                expiring_count=0,
            )

        try:
            self._credential_service.validate_no_mixed_modes(self._settings.environment)
        except ValueError as exc:
            return self._component(
                "credentials",
                "critical",
                str(exc),
                active_count=len(active_credentials),
                expiring_count=len(expiring_credentials),
            )

        if expiring_credentials:
            return self._component(
                "credentials",
                "degraded",
                "At least one active credential is expiring within the next hour.",
                active_count=len(active_credentials),
                expiring_count=len(expiring_credentials),
                expiring_profiles=expiring_credentials,
            )

        return self._component(
            "credentials",
            "ready",
            "Active credentials are available and not expiring within one hour.",
            active_count=len(active_credentials),
        )

    def _evaluate_scopes(self, event_id: str) -> ReadinessComponentStatus:
        binding = self._binding_service.get_binding_by_event_id(event_id)
        if binding is None:
            return self._component("scopes", "critical", "Cannot verify scopes without a binding.", event_id=event_id)

        latest = [record for record in self._scope_service.list_latest() if record.binding_id == binding.binding_id]
        if not latest:
            return self._component(
                "scopes",
                "critical",
                "No scope verification has been recorded for this binding.",
                binding_id=binding.binding_id,
            )

        record = latest[0]
        if record.missing_scopes:
            return self._component(
                "scopes",
                "critical",
                "Required Wix permissions are missing.",
                binding_id=binding.binding_id,
                missing_scopes=record.missing_scopes,
                verified_scopes=record.verified_scopes,
            )

        return self._component(
            "scopes",
            "ready",
            "All required Wix permissions are verified.",
            binding_id=binding.binding_id,
            verified_scopes=record.verified_scopes,
        )

    def _evaluate_manifest(self, event_id: str) -> ReadinessComponentStatus:
        status = self._manifest_service.status(event_id=event_id)
        if status.total_tickets == 0:
            return self._component(
                "manifest",
                "critical",
                "The ticket manifest has not been synced yet.",
                last_known_sync_ts=status.last_known_sync_ts,
                source_revision=status.source_revision,
            )
        if status.stale:
            return self._component(
                "manifest",
                "degraded",
                "The ticket manifest is stale and should be refreshed before doors open.",
                last_known_sync_ts=status.last_known_sync_ts,
                source_revision=status.source_revision,
                total_tickets=status.total_tickets,
            )
        return self._component(
            "manifest",
            "ready",
            "The ticket manifest is fresh.",
            last_known_sync_ts=status.last_known_sync_ts,
            source_revision=status.source_revision,
            total_tickets=status.total_tickets,
        )

    def _evaluate_redis_cache(self, event_id: str) -> ReadinessComponentStatus:
        sample_tickets = self._manifest_service.list_tickets(event_id=event_id, limit=3)
        if not sample_tickets:
            return self._component(
                "redis_cache",
                "critical",
                "No manifest tickets are available to warm the local cache.",
                event_id=event_id,
            )

        warmed = all(
            self._offline_queue.is_manifest_ticket_known(event_id=event_id, ticket_number=ticket.ticket_number)
            for ticket in sample_tickets
        )
        if not warmed:
            return self._component(
                "redis_cache",
                "critical",
                "The local Redis manifest cache is not warmed.",
                event_id=event_id,
                sample_tickets=[ticket.ticket_number for ticket in sample_tickets],
            )

        return self._component(
            "redis_cache",
            "ready",
            "The local Redis manifest cache is warmed.",
            event_id=event_id,
            sample_tickets=[ticket.ticket_number for ticket in sample_tickets],
        )

    def _evaluate_backend(self) -> ReadinessComponentStatus:
        return self._component(
            "backend",
            "ready",
            "The backend service is reachable and executing readiness checks.",
        )

    def _evaluate_worker(self) -> ReadinessComponentStatus:
        snapshots = self._worker_health.snapshot()
        required_workers = {"offline_queue_worker", "manifest_sync_worker"}
        missing = sorted(required_workers.difference(snapshots))
        stale = sorted(name for name, record in snapshots.items() if record.status != "healthy")
        if missing or stale:
            return self._component(
                "worker",
                "critical",
                "One or more background workers are missing or stale.",
                missing_workers=missing,
                stale_workers=stale,
            )

        return self._component(
            "worker",
            "ready",
            "Background workers are running and responsive.",
            workers=sorted(snapshots.keys()),
        )

    def evaluate(self, *, event_id: str, readiness_acknowledged: bool = False) -> EventReadinessReport:
        components = [
            self._evaluate_binding(event_id),
            self._evaluate_credentials(),
            self._evaluate_scopes(event_id),
            self._evaluate_manifest(event_id),
            self._evaluate_redis_cache(event_id),
            self._evaluate_backend(),
            self._evaluate_worker(),
        ]

        failed_checks = [component.name for component in components if component.status != "ready"]
        recommended_actions: list[str] = []
        for component in components:
            if component.status == "ready":
                continue
            if component.name == "binding":
                recommended_actions.append("Verify the Wix site-event binding and app installation.")
            elif component.name == "credentials":
                recommended_actions.append("Refresh or rotate the active Wix credential before opening doors.")
            elif component.name == "scopes":
                recommended_actions.append("Re-run Wix scope verification and resolve any missing permissions.")
            elif component.name == "manifest":
                recommended_actions.append("Sync the ticket manifest before activation.")
            elif component.name == "redis_cache":
                recommended_actions.append("Warm the local Redis manifest cache by syncing the active event.")
            elif component.name == "worker":
                recommended_actions.append("Restart the background workers and confirm heartbeats are healthy.")

        if any(component.status == "critical" for component in components):
            overall_status: ReadinessStatus = "critical"
        elif any(component.status == "degraded" for component in components):
            overall_status = "degraded"
        else:
            overall_status = "ready"

        return EventReadinessReport(
            event_id=event_id,
            overall_status=overall_status,
            component_statuses=components,
            failed_checks=failed_checks,
            recommended_actions=recommended_actions,
            evaluated_at=self._now(),
            readiness_acknowledged=readiness_acknowledged,
        )


_event_readiness_service: EventReadinessService | None = None


def get_event_readiness_service() -> EventReadinessService:
    global _event_readiness_service
    if _event_readiness_service is None:
        _event_readiness_service = EventReadinessService()
    return _event_readiness_service
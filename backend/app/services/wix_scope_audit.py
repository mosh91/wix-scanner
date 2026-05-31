from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from app.core.config import Settings, get_settings
from app.services.credentials import get_credential_provider
from app.services.site_event_binding import SiteEventBindingService, get_site_event_binding_service

REQUIRED_WIX_PERMISSIONS: tuple[str, ...] = (
    "WIX_EVENTS.READ_TICKETS",
    "WIX_EVENTS.CHECK-IN",
    "WIX_EVENTS.READ_EVENTS",
)


@dataclass(frozen=True)
class WixScopeAuditRecord:
    audit_id: str
    binding_id: str
    wix_site_id: str
    wix_event_id: str
    required_scopes: list[str]
    verified_scopes: list[str]
    missing_scopes: list[str]
    status: str
    alert_reason: str | None
    scopes_verified_at: str
    verified_by_actor: str
    created_at: str


class WixScopeAuditService:
    def __init__(
        self,
        *,
        settings: Settings,
        binding_service: SiteEventBindingService,
        db_path: str,
    ) -> None:
        self._settings = settings
        self._binding_service = binding_service
        self._db_path = str(Path(db_path))
        self._credential_provider = get_credential_provider(settings)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS wix_scope_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    audit_id TEXT NOT NULL UNIQUE,
                    binding_id TEXT NOT NULL,
                    wix_site_id TEXT NOT NULL,
                    wix_event_id TEXT NOT NULL,
                    required_scopes TEXT NOT NULL,
                    verified_scopes TEXT NOT NULL,
                    missing_scopes TEXT NOT NULL,
                    status TEXT NOT NULL,
                    alert_reason TEXT,
                    scopes_verified_at TEXT NOT NULL,
                    verified_by_actor TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _now(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _fetch_live_permissions(self) -> list[str]:
        token = self._credential_provider.get_wix_api_token()
        if not token:
            raise RuntimeError("Wix API token not configured.")

        url = f"{self._settings.wix_base_url.rstrip('/')}/apps/v1/instance"
        headers = {"Authorization": f"Bearer {token}"}

        with httpx.Client(timeout=self._settings.wix_timeout_ms / 1000.0) as client:
            response = client.get(url, headers=headers)

        if response.status_code >= 400:
            raise RuntimeError(f"Wix app instance query failed with {response.status_code}")

        data = response.json() if response.content else {}
        instance = data.get("instance", {}) if isinstance(data, dict) else {}
        permissions = instance.get("permissions", []) if isinstance(instance, dict) else []
        if not isinstance(permissions, list):
            return []
        return sorted({str(item).strip() for item in permissions if str(item).strip()})

    def _fetch_permissions_for_site(self, wix_site_id: str) -> list[str]:
        if self._settings.wix_mock_mode:
            if not wix_site_id.startswith("site-"):
                return []
            if wix_site_id.endswith("-missing-scopes"):
                return [
                    "WIX_EVENTS.CHECK-IN",
                    "WIX_EVENTS.READ_EVENTS",
                ]
            return list(REQUIRED_WIX_PERMISSIONS)

        return self._fetch_live_permissions()

    def _insert_audit(
        self,
        *,
        binding_id: str,
        wix_site_id: str,
        wix_event_id: str,
        required_scopes: list[str],
        verified_scopes: list[str],
        missing_scopes: list[str],
        status: str,
        alert_reason: str | None,
        actor: str,
    ) -> WixScopeAuditRecord:
        now = self._now()
        audit_id = f"scope-{uuid4()}"

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO wix_scope_audit (
                    audit_id,
                    binding_id,
                    wix_site_id,
                    wix_event_id,
                    required_scopes,
                    verified_scopes,
                    missing_scopes,
                    status,
                    alert_reason,
                    scopes_verified_at,
                    verified_by_actor,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    binding_id,
                    wix_site_id,
                    wix_event_id,
                    json.dumps(required_scopes),
                    json.dumps(verified_scopes),
                    json.dumps(missing_scopes),
                    status,
                    alert_reason,
                    now,
                    actor,
                    now,
                ),
            )
            conn.commit()

        return WixScopeAuditRecord(
            audit_id=audit_id,
            binding_id=binding_id,
            wix_site_id=wix_site_id,
            wix_event_id=wix_event_id,
            required_scopes=required_scopes,
            verified_scopes=verified_scopes,
            missing_scopes=missing_scopes,
            status=status,
            alert_reason=alert_reason,
            scopes_verified_at=now,
            verified_by_actor=actor,
            created_at=now,
        )

    def verify_scopes(self, *, binding_id: str, actor: str) -> WixScopeAuditRecord:
        binding = self._binding_service.get_binding(binding_id)
        if binding.status != "verified":
            raise PermissionError("Scope verification requires a verified site-event binding")

        required = list(REQUIRED_WIX_PERMISSIONS)
        verified = self._fetch_permissions_for_site(binding.wix_site_id)
        verified_set = set(verified)
        missing = [scope for scope in required if scope not in verified_set]

        if missing:
            status = "warning"
            alert_reason = f"Missing required Wix permissions: {', '.join(missing)}"
        else:
            status = "green"
            alert_reason = None

        return self._insert_audit(
            binding_id=binding.binding_id,
            wix_site_id=binding.wix_site_id,
            wix_event_id=binding.wix_event_id,
            required_scopes=required,
            verified_scopes=verified,
            missing_scopes=missing,
            status=status,
            alert_reason=alert_reason,
            actor=actor,
        )

    def _row_to_record(self, row: sqlite3.Row) -> WixScopeAuditRecord:
        return WixScopeAuditRecord(
            audit_id=row["audit_id"],
            binding_id=row["binding_id"],
            wix_site_id=row["wix_site_id"],
            wix_event_id=row["wix_event_id"],
            required_scopes=json.loads(row["required_scopes"]),
            verified_scopes=json.loads(row["verified_scopes"]),
            missing_scopes=json.loads(row["missing_scopes"]),
            status=row["status"],
            alert_reason=row["alert_reason"],
            scopes_verified_at=row["scopes_verified_at"],
            verified_by_actor=row["verified_by_actor"],
            created_at=row["created_at"],
        )

    def list_latest(self) -> list[WixScopeAuditRecord]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT a.*
                FROM wix_scope_audit a
                INNER JOIN (
                    SELECT binding_id, MAX(created_at) AS max_created_at
                    FROM wix_scope_audit
                    GROUP BY binding_id
                ) latest
                ON a.binding_id = latest.binding_id AND a.created_at = latest.max_created_at
                ORDER BY a.created_at DESC
                """
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_history_for_binding(self, binding_id: str, limit: int = 20) -> list[WixScopeAuditRecord]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM wix_scope_audit
                WHERE binding_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (binding_id, max(1, min(limit, 100))),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]


_scope_audit_service: WixScopeAuditService | None = None


def set_wix_scope_audit_service(service: WixScopeAuditService) -> None:
    global _scope_audit_service
    _scope_audit_service = service


def get_wix_scope_audit_service() -> WixScopeAuditService:
    global _scope_audit_service
    if _scope_audit_service is None:
        settings = get_settings()
        _scope_audit_service = WixScopeAuditService(
            settings=settings,
            binding_service=get_site_event_binding_service(),
            db_path=settings.site_event_binding_db_path,
        )
    return _scope_audit_service

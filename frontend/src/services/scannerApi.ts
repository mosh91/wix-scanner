export type ScanResultStatus = "CHECKED_IN" | "INVALID_TICKET" | "ALREADY_CHECKED_IN" | "QUEUED_OFFLINE";

export type ScanResponse = {
  status: ScanResultStatus;
  accepted: boolean;
  ticket_number: string;
  reason: string | null;
  error_code: string;
  wix_status: string;
  response_time_ms: number;
  idempotency_key: string;
};

export type ScannerHealthResponse = {
  backend_status: "green" | "yellow" | "red";
  in_flight: number;
  success_rate: number;
  last_20_response_times: number[];
  min_ms: number;
  max_ms: number;
  avg_ms: number;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
  last_check_ts: number;
  manifest_cache_stale: boolean;
};

export type ScanSubmitContext = {
  source?: string;
  sessionId?: string;
  operatorId?: string;
  scanEventId?: string;
  scannerStatus?: string;
  activeEventId?: string;
  activeStationId?: string;
};

export type WebhookDeliveryRecord = {
  id: number;
  wix_request_id: string | null;
  wix_event_id: string;
  ticket_number: string;
  source: string;
  checked_in_at: string;
  signature_valid: boolean;
  status: string;
  error_message: string | null;
  received_at: number;
  retried_from_id: number | null;
};

export type WebhookRetryResponse = {
  acknowledged: boolean;
  outcome: string;
  message: string;
  delivery_id: number;
};

export type SiteEventBindingStatus = "pending" | "verified" | "unverified" | "revoked";
export type AppInstallationStatus = "pending_install" | "installed" | "uninstalled" | "failed";

export type SiteEventBindingRecord = {
  binding_id: string;
  wix_site_id: string;
  wix_event_id: string;
  status: SiteEventBindingStatus;
  app_installation_status: AppInstallationStatus;
  credential_profile_id: string | null;
  sync_policy_profile_id: string | null;
  binding_created_at: string;
  binding_verified_at: string | null;
  verified_by_actor: string | null;
  last_verification_error: string | null;
  verification_evidence: Record<string, unknown>;
};

export type CreateSiteEventBindingRequest = {
  wix_site_id: string;
  wix_event_id: string;
  actor?: string;
  verify_immediately?: boolean;
  credential_profile_id?: string;
  sync_policy_profile_id?: string;
};

export type ActivateEventResponse = {
  wix_event_id: string;
  status: string;
  activated_at: string;
  activated_by_actor: string;
};

export type VerifiedEventRecord = {
  wix_event_id: string;
  wix_site_id: string;
};

export type WixScopeAuditRecord = {
  audit_id: string;
  binding_id: string;
  wix_site_id: string;
  wix_event_id: string;
  required_scopes: string[];
  verified_scopes: string[];
  missing_scopes: string[];
  status: "green" | "warning";
  alert_reason: string | null;
  scopes_verified_at: string;
  verified_by_actor: string;
  created_at: string;
};

// ─── Bootstrap API ──────────────────────────────────────────────────────────

export const BOOTSTRAP_QR_PREFIX = "BOOTSTRAP:v1:";
export const ADMIN_BOOTSTRAP_QR_PREFIX = "ADMIN_BOOTSTRAP:v1:";

export type BootstrapValidateRequest = {
  payload: string;
  current_event_id?: string;
};

export type BootstrapSessionResponse = {
  bootstrap_session_id: string;
  event_id: string;
  station_id: string;
  expires_at: number;
  is_admin_override: boolean;
};

/** Returns true if the scanned payload is a kiosk bootstrap QR (normal or admin). */
export function isBootstrapQR(payload: string): boolean {
  return (
    payload.startsWith(BOOTSTRAP_QR_PREFIX) ||
    payload.startsWith(ADMIN_BOOTSTRAP_QR_PREFIX)
  );
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

export async function submitScan(payload: string, context: ScanSubmitContext = {}): Promise<ScanResponse> {
  const {
    source = "hid",
    sessionId = "session-local",
    operatorId = "operator-local",
    scanEventId = crypto.randomUUID(),
    scannerStatus = "connected",
    activeEventId,
    activeStationId,
  } = context;
  const response = await fetch(`${API_BASE}/checkins/scan`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      payload,
      source,
      session_id: sessionId,
      operator_id: operatorId,
      scan_event_id: scanEventId,
      scanner_status: scannerStatus,
      active_event_id: activeEventId ?? null,
      active_station_id: activeStationId ?? null,
    }),
  });

  if (!response.ok) {
    throw new Error(`Scan failed with status ${response.status}`);
  }

  return (await response.json()) as ScanResponse;
}

export async function fetchScannerHealth(eventId?: string): Promise<ScannerHealthResponse> {
  const query = eventId ? `?event_id=${encodeURIComponent(eventId)}` : "";
  const response = await fetch(`${API_BASE}/health/scanner${query}`);
  if (!response.ok) {
    throw new Error(`Health check failed with status ${response.status}`);
  }
  return (await response.json()) as ScannerHealthResponse;
}

export async function validateBootstrapQR(
  request: BootstrapValidateRequest,
): Promise<BootstrapSessionResponse> {
  const response = await fetch(`${API_BASE}/bootstrap/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    const detail =
      (errorData as { detail?: string }).detail ??
      `Bootstrap validation failed (${response.status})`;
    throw new Error(detail);
  }

  return (await response.json()) as BootstrapSessionResponse;
}

export async function clearBootstrapSession(bootstrapSessionId: string): Promise<void> {
  await fetch(`${API_BASE}/bootstrap/clear`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bootstrap_session_id: bootstrapSessionId }),
  });
}

export async function fetchWebhookHistory(limit = 25): Promise<WebhookDeliveryRecord[]> {
  const response = await fetch(`${API_BASE}/webhooks/wix/checkins/history?limit=${limit}`);
  if (!response.ok) {
    throw new Error(`Webhook history failed with status ${response.status}`);
  }
  return (await response.json()) as WebhookDeliveryRecord[];
}

export async function retryWebhookDelivery(deliveryId: number): Promise<WebhookRetryResponse> {
  const response = await fetch(`${API_BASE}/webhooks/wix/checkins/history/${deliveryId}/retry`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`Webhook retry failed with status ${response.status}`);
  }
  return (await response.json()) as WebhookRetryResponse;
}

export async function createSiteEventBinding(
  request: CreateSiteEventBindingRequest,
): Promise<SiteEventBindingRecord> {
  const response = await fetch(`${API_BASE}/admin/site-event-bindings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw new Error(`Create site-event binding failed with status ${response.status}`);
  }
  return (await response.json()) as SiteEventBindingRecord;
}

export async function listSiteEventBindings(): Promise<SiteEventBindingRecord[]> {
  const response = await fetch(`${API_BASE}/admin/site-event-bindings`);
  if (!response.ok) {
    throw new Error(`List site-event bindings failed with status ${response.status}`);
  }
  return (await response.json()) as SiteEventBindingRecord[];
}

export async function verifySiteEventBinding(bindingId: string, actor = "operator-ui"): Promise<SiteEventBindingRecord> {
  const response = await fetch(`${API_BASE}/admin/site-event-bindings/${bindingId}/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor }),
  });
  if (!response.ok) {
    throw new Error(`Verify binding failed with status ${response.status}`);
  }
  return (await response.json()) as SiteEventBindingRecord;
}

export async function listVerifiedEvents(): Promise<VerifiedEventRecord[]> {
  const response = await fetch(`${API_BASE}/admin/events`);
  if (!response.ok) {
    throw new Error(`List verified events failed with status ${response.status}`);
  }
  return (await response.json()) as VerifiedEventRecord[];
}

export async function activateEvent(wixEventId: string, actor = "operator-ui"): Promise<ActivateEventResponse> {
  const response = await fetch(`${API_BASE}/admin/events/${encodeURIComponent(wixEventId)}/activate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor }),
  });
  if (!response.ok) {
    throw new Error(`Activate event failed with status ${response.status}`);
  }
  return (await response.json()) as ActivateEventResponse;
}

export async function verifyBindingScopes(bindingId: string, actor = "security-admin-ui"): Promise<WixScopeAuditRecord> {
  const response = await fetch(`${API_BASE}/admin/site-event-bindings/${bindingId}/scopes/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor }),
  });
  if (!response.ok) {
    throw new Error(`Verify binding scopes failed with status ${response.status}`);
  }
  return (await response.json()) as WixScopeAuditRecord;
}

export async function listLatestScopeAudits(): Promise<WixScopeAuditRecord[]> {
  const response = await fetch(`${API_BASE}/admin/scopes/latest`);
  if (!response.ok) {
    throw new Error(`List scope audits failed with status ${response.status}`);
  }
  return (await response.json()) as WixScopeAuditRecord[];
}

// ─── Credential Lifecycle API ────────────────────────────────────────────────

export type CredentialLifecycleState =
  | "created"
  | "validated"
  | "active"
  | "expiring_soon"
  | "rotation_pending"
  | "revoked"
  | "failed";

export type AuthMode = "oauth" | "api_key";

export type CredentialLifecycleRecord = {
  credential_id: string;
  profile_name: string;
  auth_mode: AuthMode;
  lifecycle_state: CredentialLifecycleState;
  created_at: string;
  validated_at: string | null;
  activated_at: string | null;
  last_validated_at: string | null;
  validation_error: string | null;
  expires_at: string | null;
  rotation_note: string | null;
  created_by_actor: string;
};

export type CredentialLifecycleEvent = {
  event_id: string;
  credential_id: string;
  from_state: string | null;
  to_state: string;
  actor: string;
  event_note: string | null;
  occurred_at: string;
};

export type AuthStrategyEntry = {
  scope: string;
  production_mode: string;
  staging_mode: string;
  notes: string;
};

export type AuthStrategyResponse = {
  strategy: Record<string, AuthStrategyEntry>;
  environment: string;
  configured_auth_mode: string;
};

export type RotateCredentialResponse = {
  new_credential: CredentialLifecycleRecord;
  revoked_credential: CredentialLifecycleRecord;
};

export async function createCredential(
  profileName: string,
  authMode: AuthMode,
  actor = "operator-ui",
  expiresAt?: string,
): Promise<CredentialLifecycleRecord> {
  const response = await fetch(`${API_BASE}/admin/credentials`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      profile_name: profileName,
      auth_mode: authMode,
      actor,
      expires_at: expiresAt ?? null,
    }),
  });
  if (!response.ok) {
    throw new Error(`Create credential failed with status ${response.status}`);
  }
  return (await response.json()) as CredentialLifecycleRecord;
}

export async function validateCredential(
  credentialId: string,
  actor = "operator-ui",
): Promise<CredentialLifecycleRecord> {
  const response = await fetch(`${API_BASE}/admin/credentials/${encodeURIComponent(credentialId)}/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor }),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? `Validate credential failed (${response.status})`);
  }
  return (await response.json()) as CredentialLifecycleRecord;
}

export async function activateCredential(
  credentialId: string,
  actor = "operator-ui",
): Promise<CredentialLifecycleRecord> {
  const response = await fetch(`${API_BASE}/admin/credentials/${encodeURIComponent(credentialId)}/activate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor }),
  });
  if (!response.ok) {
    throw new Error(`Activate credential failed with status ${response.status}`);
  }
  return (await response.json()) as CredentialLifecycleRecord;
}

export async function rotateCredential(
  credentialId: string,
  newProfileName: string,
  newAuthMode: AuthMode,
  actor = "operator-ui",
  newExpiresAt?: string,
): Promise<RotateCredentialResponse> {
  const response = await fetch(`${API_BASE}/admin/credentials/${encodeURIComponent(credentialId)}/rotate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      new_profile_name: newProfileName,
      new_auth_mode: newAuthMode,
      actor,
      new_expires_at: newExpiresAt ?? null,
    }),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? `Rotate credential failed (${response.status})`);
  }
  return (await response.json()) as RotateCredentialResponse;
}

export async function revokeCredential(
  credentialId: string,
  actor = "operator-ui",
  note?: string,
): Promise<CredentialLifecycleRecord> {
  const response = await fetch(`${API_BASE}/admin/credentials/${encodeURIComponent(credentialId)}/revoke`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor, note: note ?? null }),
  });
  if (!response.ok) {
    throw new Error(`Revoke credential failed with status ${response.status}`);
  }
  return (await response.json()) as CredentialLifecycleRecord;
}

export async function listCredentials(): Promise<CredentialLifecycleRecord[]> {
  const response = await fetch(`${API_BASE}/admin/credentials`);
  if (!response.ok) {
    throw new Error(`List credentials failed with status ${response.status}`);
  }
  return (await response.json()) as CredentialLifecycleRecord[];
}

export async function listCredentialEvents(credentialId: string): Promise<CredentialLifecycleEvent[]> {
  const response = await fetch(`${API_BASE}/admin/credentials/${encodeURIComponent(credentialId)}/events`);
  if (!response.ok) {
    throw new Error(`List credential events failed with status ${response.status}`);
  }
  return (await response.json()) as CredentialLifecycleEvent[];
}

export async function getAuthStrategy(): Promise<AuthStrategyResponse> {
  const response = await fetch(`${API_BASE}/admin/credentials/auth-strategy/decision-table`);
  if (!response.ok) {
    throw new Error(`Get auth strategy failed with status ${response.status}`);
  }
  return (await response.json()) as AuthStrategyResponse;
}

export async function validateAuthModeConsistency(): Promise<{ ok: boolean; error?: string }> {
  const response = await fetch(`${API_BASE}/admin/credentials/auth-strategy/validate-consistency`, {
    method: "POST",
  });
  if (response.status === 422) {
    const err = await response.json().catch(() => ({}));
    return { ok: false, error: (err as { detail?: string }).detail ?? "Mixed auth modes detected" };
  }
  if (!response.ok) {
    throw new Error(`Validate auth mode consistency failed with status ${response.status}`);
  }
  return { ok: true };
}


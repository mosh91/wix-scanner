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

export type ScanResultStatus = "CHECKED_IN" | "INVALID_TICKET" | "ALREADY_CHECKED_IN";

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
  last_check_ts: number;
};

export type ScanSubmitContext = {
  source?: string;
  sessionId?: string;
  operatorId?: string;
  scannerStatus?: string;
};

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

export async function submitScan(payload: string, context: ScanSubmitContext = {}): Promise<ScanResponse> {
  const { source = "hid", sessionId = "session-local", operatorId = "operator-local", scannerStatus = "connected" } = context;
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
      scanner_status: scannerStatus,
    }),
  });

  if (!response.ok) {
    throw new Error(`Scan failed with status ${response.status}`);
  }

  return (await response.json()) as ScanResponse;
}

export async function fetchScannerHealth(): Promise<ScannerHealthResponse> {
  const response = await fetch(`${API_BASE}/health/scanner`);
  if (!response.ok) {
    throw new Error(`Health check failed with status ${response.status}`);
  }
  return (await response.json()) as ScannerHealthResponse;
}

# Backend Environment Setup

This file explains every variable in [backend/.env.example](backend/.env.example), what it does, and what to set in development vs production.

## Quick answers

- Your bootstrap payload is valid if `/api/bootstrap/validate` accepts it.
- If kiosk says "invalid bootstrap QR", the most common issue is that the QR encodes the whole JSON response instead of only `qr_payload`.
- `WIX_SCANNER_WIX_MOCK_MODE` controls whether backend uses mocked Wix behavior (`true`) or real Wix API calls (`false`).

## Bootstrap QR troubleshooting

1. Generate payload:

```bash
curl -s "http://localhost:8000/api/bootstrap/generate?event_id=evento-001&station_id=puerta-a&ttl_seconds=43200"
```

2. Use only this field as QR text:

- `qr_payload`

3. Validate payload directly:

```bash
curl -s -X POST "http://localhost:8000/api/bootstrap/validate" \
  -H "Content-Type: application/json" \
  -d '{"payload":"BOOTSTRAP:v1:..."}'
```

If step 3 succeeds, backend signing and secret are correct.
If kiosk still fails, check scanner behavior:

- Scanner sends full QR content + Enter terminator.
- Payload must remain ASCII and start with `BOOTSTRAP:v1:` or `ADMIN_BOOTSTRAP:v1:`.
- Do not include JSON braces, quotes, or extra wrapper text.

## Variable reference

### Core app

- `WIX_SCANNER_APP_NAME`
  - Purpose: FastAPI app title.
  - Dev: `Wix Scanner Backend`
  - Prod: Any descriptive service name.

- `WIX_SCANNER_ENVIRONMENT`
  - Purpose: Environment mode; used for guards (for example bootstrap generate endpoint blocked in production).
  - Dev: `development`
  - Prod: `production`

- `WIX_SCANNER_API_V1_PREFIX`
  - Purpose: API prefix.
  - Dev/Prod: `/api`

- `WIX_SCANNER_CORS_ORIGINS`
  - Purpose: Allowed browser origins.
  - Dev: `["http://localhost:5173"]`
  - Prod: Your real frontend domains only.

### Bootstrap and security

- `WIX_SCANNER_BOOTSTRAP_SECRET`
  - Purpose: HMAC signing/validation for bootstrap QR payloads.
  - Dev: Any non-default secret.
  - Prod: Strong random secret, rotate safely.

- `WIX_SCANNER_CREDENTIAL_ENCRYPTION_KEY`
  - Purpose: Encryption key for credential storage paths that use DB provider logic.
  - Dev: Non-default local value.
  - Prod: Strong secret from secret manager.

### Wix integration

- `WIX_SCANNER_WIX_MOCK_MODE`
  - Purpose: Toggle Wix client behavior.
  - `true`: Simulated Wix responses for local/dev testing.
  - `false`: Real calls to Wix APIs.
  - Recommendation:
    - Local UI/dev flow testing: `true` is fine.
    - Real event checks, readiness, and production: set `false`.

- `WIX_SCANNER_CREDENTIAL_PROVIDER_MODE`
  - Purpose: Credential source strategy.
  - Values: `env` or `db`.
  - Dev: usually `env`.
  - Prod: `db` or managed secret strategy, depending on your runbook.

- `WIX_SCANNER_WIX_API_TOKEN`
  - Purpose: Wix API token used when provider mode is `env`.
  - Dev: optional in full mock mode.
  - Prod/real testing: required when using `env` mode.

- `WIX_SCANNER_WIX_TIMEOUT_MS`
  - Purpose: Outbound Wix request timeout.
  - Dev default: `2500`
  - Prod: tune to your network behavior.

- `WIX_SCANNER_WIX_MAX_RETRIES`
  - Purpose: Retry attempts for Wix calls.
  - Dev default: `3`

- `WIX_SCANNER_WIX_RETRY_BASE_MS`
  - Purpose: Initial backoff.
  - Dev default: `150`

- `WIX_SCANNER_WIX_RETRY_MAX_MS`
  - Purpose: Maximum backoff cap.
  - Dev default: `1500`

- `WIX_SCANNER_WIX_WEBHOOK_SECRET`
  - Purpose: Secret used to verify Wix webhook signature for `/api/webhooks/wix/checkins`.
  - Dev: non-default value shared with your webhook sender.
  - Prod: strong secret in secret manager.

### Data and storage paths

- `WIX_SCANNER_CREDENTIAL_DB_PATH`
  - Purpose: SQLite path for credential provider DB mode.
  - Dev default: `./data/credentials.db`

- `WIX_SCANNER_SITE_EVENT_BINDING_DB_PATH`
  - Purpose: SQLite path for site/event binding data.
  - Dev default: `./data/site_event_bindings.db`

- `WIX_SCANNER_RECONCILIATION_DB_PATH`
  - Purpose: SQLite path for reconciliation data.
  - Dev default: `./data/reconciliation.db`

### Redis and offline queue

- `WIX_SCANNER_REDIS_URL`
  - Purpose: Redis connection string.
  - Dev (docker compose): `redis://redis:6379/0`

- `WIX_SCANNER_REDIS_KEY_PREFIX`
  - Purpose: Namespace prefix for Redis keys.
  - Dev default: `wix-scanner`

- `WIX_SCANNER_PENDING_MARKER_TTL_S`
  - Purpose: TTL for pending dedupe markers.
  - Dev default: `86400`

- `WIX_SCANNER_MANIFEST_CACHE_TTL_S`
  - Purpose: TTL for manifest cache freshness.
  - Dev default: `86400`

- `WIX_SCANNER_OFFLINE_QUEUE_MAX_ATTEMPTS`
  - Purpose: Max retries before dead-letter behavior.
  - Dev default: `5`

- `WIX_SCANNER_OFFLINE_QUEUE_WORKER_INTERVAL_S`
  - Purpose: Worker polling interval.
  - Dev default: `2`

### Relay

- `WIX_SCANNER_RELAY_AUTH_TOKEN`
  - Purpose: Shared auth token for relay-to-cloud API protection.
  - Dev: non-default local token.
  - Prod: strong secret.

- `WIX_SCANNER_RELAY_SIGNING_SECRET`
  - Purpose: HMAC signing secret for relay payload integrity.
  - Dev: non-default local secret.
  - Prod: strong secret.

- `WIX_SCANNER_RELAY_PROTOCOL_VERSION`
  - Purpose: Relay contract version gate.
  - Dev default: `2026-05-29`
  - Prod: keep in sync between relay and backend.

## Recommended setup order (validated against project APIs and Wix docs)

1. Configure secrets and environment (`BOOTSTRAP_SECRET`, `WIX_WEBHOOK_SECRET`, token/provider mode).
2. Configure Wix integration mode:
   - dev smoke tests: mock mode can stay `true`.
   - real integration tests and event operations: set mock mode `false`.
3. Create and verify site-event binding (`/api/admin/site-event-bindings`).
4. Verify scopes (`/api/admin/site-event-bindings/{binding_id}/scopes/verify`).
5. Create/validate/activate credential (`/api/admin/credentials...`).
6. Sync manifest (`/api/manifest/sync`).
7. Check readiness (`/api/admin/events/{event_id}/readiness`).
8. Activate event (`/api/admin/events/{event_id}/activate`).
9. Generate bootstrap payload and enroll each kiosk.
10. Run reconciliation during/post event (`/api/admin/events/{event_id}/reconciliation/run`).

## Wix MCP validation notes

The setup order above is consistent with:

- Wix Events Tickets check-in API endpoint:
  - `POST https://www.wixapis.com/events/v1/tickets/check-in`
  - Docs: https://dev.wix.com/docs/api-reference/business-solutions/events/registration/ticketing/tickets/check-in-ticket

- Wix Tickets API prerequisites (Events app installed on site):
  - Docs: https://dev.wix.com/docs/api-reference/business-solutions/events/registration/ticketing/tickets/introduction

These external docs align with backend routes and readiness gates implemented in this repository.

## Mock Ticket QR Catalog (for `WIX_SCANNER_WIX_MOCK_MODE=true`)

Use these payloads as the QR content (text encoded in the QR image).

Important:

- For mock tests, the ticket outcome is determined by ticket text patterns.
- Real Wix ticket ownership/check-in truth is not validated while mock mode is enabled.

### 1) Success (CHECKED_IN)

QR payload text examples:

- `TICKET-12345`
- `eventId=evento-001;ticketNumber=TICKET-12345`

Expected result:

- `status=CHECKED_IN`

### 2) Duplicate simulation (ALREADY_CHECKED_IN)

QR payload text examples:

- `DUP-12345`
- `ALREADY-12345`
- `eventId=evento-001;ticketNumber=DUP-12345`

Expected result:

- `status=ALREADY_CHECKED_IN`

### 3) Rate-limit simulation (QUEUED_OFFLINE if ticket exists in local manifest cache)

QR payload text examples:

- `RATE-12345`
- `eventId=evento-001;ticketNumber=RATE-12345`

Expected result:

- Usually `status=INVALID_TICKET` unless the ticket is known in local manifest cache.
- If known in manifest cache, then `status=QUEUED_OFFLINE` path can be exercised.

### 4) Upstream 5xx simulation (QUEUED_OFFLINE if ticket exists in local manifest cache)

QR payload text examples:

- `WIX5XX-12345`
- `eventId=evento-001;ticketNumber=WIX5XX-12345`

Expected result:

- Usually `status=INVALID_TICKET` unless the ticket is known in local manifest cache.
- If known in manifest cache, then `status=QUEUED_OFFLINE` path can be exercised.

### 5) Forced invalid parsing

QR payload text examples:

- `INVALID-12345`

Expected result:

- `status=INVALID_TICKET`

### 6) Wix Events URL format parsing test

QR payload text example:

- `https://www.wixevents.com/check-in/ABC123,evento-001`

Expected result in mock mode:

- URL format is parsed correctly (`ticketNumber=ABC123`, `eventId=evento-001`).
- Outcome still follows mock behavior, not real Wix state.

## Optional: quick local API test without generating QR image

You can test scanner outcomes directly with API calls:

```bash
curl -s -X POST "http://localhost:8000/api/checkins/scan" \
  -H "Content-Type: application/json" \
  -d '{"payload":"TICKET-12345","active_event_id":"evento-001"}'
```

Replace payload with any catalog value above.

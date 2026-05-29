# Wix Scanner Implementation Stories

This document turns the project plan into sequential user stories with concrete tasks and acceptance criteria.

## How to Use This File

1. Implement stories in the listed order.
2. Do not start a dependent story until blocking stories are complete.
3. Mark each story as Done only when all acceptance criteria pass.
4. Link each story to code PRs, tests, and runbook updates.

---

## Critical Additions for Wix Integration (NEW)

This iteration adds **critical Phase 1 and Phase 4B stories** addressing architectural gaps for real Wix event integration. Key areas:

**Phase 1 — Moved Earlier (Stories 11–15):**
- **P1-US-11:** Site-event binding and app installation verification — prevents auth to wrong accounts.
- **P1-US-12:** OAuth scope verification — ensures check-in and read permissions are present before go-live.
- **P1-US-13:** Credential lifecycle state machine — defines auth mode (OAuth vs API key) upfront and enforces consistency.
- **P1-US-14:** Event readiness gate — automated pre-flight check covering credentials, scopes, ticket cache, and relay health.
- **P1-US-15:** Reconciliation contract — defines drift states and deterministic conflict resolution with Wix as source of truth.

**Phase 4B — Operational Validation (Stories 01–05):**
- **P4B-US-01:** Wix MCP integration verification script — repeatable env-specific validation in CI/CD.
- **P4B-US-02:** Pre-event runbook and checklist — 1-week through post-event operational timeline.
- **P4B-US-03:** Live event drill — verify recovery from network outage + relay restart with no duplicates.
- **P4B-US-04:** Credential rotation drill — prove zero-downtime rotation under event load.
- **P4B-US-05:** Operator incident response training — hands-on guides for common failure scenarios.

**Why These Matter:**
- Wix integration is high-risk; binding, scope, and auth strategy decisions must be locked in Phase 1 MVp, not discovered later.
- Reconciliation contract ensures Wix remains source of truth and local queue does not drift indefinitely.
- Pre-event readiness gate prevents "event day surprises" (expired token, missing scope, stale cache).
- Operational drills validate the system before real venue usage; "first drill is first failure" risk is unacceptable for ticketed events.

---

## Story Status Legend

- `Not Started`
- `In Progress`
- `Blocked`
- `Done`

---

## Phase 1: Core Functionality and MVP

### Story P1-US-01: Bootstrap backend and frontend foundations
Status: `Completed`

User story:
As a developer, I want a working FastAPI + React project skeleton so we can build features quickly.

Tasks:
- Create backend project with FastAPI app, routing module, settings module, and health endpoint.
- Create frontend project with React + Vite app shell and route placeholders.
- Install and configure Tailwind CSS with the shadcn/ui preset.
- Initialize shadcn/ui component registry and install baseline components (`Card`, `Badge`, `Button`, `Separator`).
- Install and configure Sonner for toast notifications (add `<Toaster />` to app root).
- Add shared environment configuration templates for backend and frontend.
- Add local developer scripts for run, test, lint, and format.
- Add Docker Compose baseline for backend, frontend, and Redis.
- Set up i18n framework (e.g., i18next or react-i18next) with Spanish as default language.
- Create base translation files structure (en.json, es.json) with common UI strings including kiosk state messages.
- Configure language detection and locale preference storage.

Acceptance criteria:
- Given a fresh clone, when I run the documented startup steps, then backend, frontend, and Redis start successfully.
- Given the backend is running, when I request `/api/health`, then I receive HTTP 200 with service status.
- Given the frontend is running, when I open the app, then the base layout and navigation render without errors using shadcn components and Tailwind classes.
- Given the app loads, when checking browser console, then app initializes with Spanish as default language.
- Given UI strings exist, when viewed in app, then Spanish translations are displayed for all static content.
- Given Sonner is configured, when `toast()` is called from any component, then a toast notification appears correctly.

---

### Story P1-US-02: HID scanner capture on operator screen
Status: `Done`

User story:
As a check-in operator, I want scanner input captured reliably so I can scan tickets quickly without manual typing.

Tasks:
- [x] Build Operator Check-In screen implementing the 3-state full-screen kiosk UI (Idle / Success / Error) using shadcn `Card`, Tailwind full-viewport classes, and text sizes `text-5xl` or larger for kiosk readability at one metre distance.
- [x] Implement a global `useHIDScanner` hook that attaches a `keydown` listener on `window`. HID scanners emit keyboard characters at burst speed and send `Enter` as the terminator. The global hook captures input regardless of focus state — no hidden input field or focus watchdog is needed.
- [x] Buffer incoming characters in the hook, flush on `Enter` (configurable terminator key), and apply a short debounce (50 ms default) to coalesce scanner burst input.
- [x] Validate payload length and character set before dispatching to the API.
- [x] **Idle state:** dark/deep-blue full-screen background, `animate-pulse` ring around scan icon, message `"Por favor, acerque su código QR o Ticket al escáner"`.
- [x] **Success state:** `bg-emerald-500` full-screen, giant `CheckCircle` icon, text `"¡ACCESO CONCEDIDO!"` at `text-7xl`, auto-returns to Idle after 2.5 s. Optionally display ticket number below.
- [x] **Error state:** `bg-rose-600` full-screen, giant alert icon, text `"TICKET INVÁLIDO o YA PROCESADO"` at `text-7xl`, specific rejection reason below, auto-returns to Idle after 3 s or on next scan.
- [x] Show a neutral "processing" overlay only if API response exceeds 300 ms.
- [x] Use Sonner `toast` for secondary operator notifications (e.g. offline queue warning, scanner disconnected) that do not need to block the full screen.
- [x] Add configurable debounce and max payload length validation.
- [x] **Implement WebHID API integration for scanner detection and health**:
  - [x] Use WebHID API to enumerate and detect connected USB HID scanner devices.
  - [x] Request user permission to access scanner device on first use (browser security model).
  - [x] Monitor device connection/disconnection events in real-time.
  - [x] Implement device health check: send test request to scanner to verify responsiveness.
  - [x] Handle graceful fallback if WebHID is unavailable (keyboard input as fallback).
  - [x] Store permitted device IDs in browser storage for seamless reconnection.
- [x] **Add real-time health status indicators to scanner screen**:
  - [x] Scanner USB connection status via WebHID (connected/disconnected badge with vendor/model info if available)
  - [x] Scanner device health indicator (responding/unresponsive based on device comms)
  - [x] Input focus state indicator (visual feedback showing focus is active)
  - [x] Backend connectivity status (green/yellow/red indicator with last check timestamp)
  - [x] WebSocket connection status (if applicable, showing real-time sync state)
- [x] **Implement response metrics display**:
  - [x] Current response time display (last request latency in ms)
  - [x] Response time history (last 10-20 responses with min/max/average)
  - [x] Success/error rate indicator (e.g., "98% success last hour")
- [x] **Add metrics collection service**:
  - [x] Collect response time, timestamp, success/failure status for each scan
  - [x] Track concurrent request count
  - [x] Persist scan metrics to backend DB for later analysis
  - [x] Include scanner session metadata (session ID, operator info)
- [x] **Display current and recent scan history**:
  - [x] Show prominently the current/last scanned ticket number on the operator screen.
  - [x] Maintain and display a rolling list of the last 25 scanned ticket numbers with status (success/error/duplicate).
  - [x] Include timestamps and result status for each recent ticket in the history list.
  - [x] Allow operator to click history items to view detailed scan info (response time, Wix status, etc.).

Acceptance criteria:
- Given the Operator screen is active, when a scanner sends QR text ending with Enter, then one scan payload is submitted.
- Given focus is lost, when a scan is attempted, then the UI warns and restores scanner-ready state.
- Given rapid scans, when 20 tickets are scanned in sequence, then each scan is processed exactly once by the frontend.
- **Given a USB HID scanner is plugged in, when the Operator screen loads, then WebHID API detects the device and shows connected status with device info.**
- **Given WebHID detects a scanner connection, when user grants permission (first use), then device is remembered for future sessions.**
- **Given a connected scanner is unplugged, when device disconnect event fires, then UI immediately reflects disconnected state.**
- **Given scanner is connected but unresponsive, when health check runs (every 10s), then UI indicates unresponsive state (yellow indicator).**
- **Given WebHID is unavailable or blocked, when fallback is triggered, then app gracefully accepts keyboard input for scanning without errors.**
- **Given the scanner screen is active, when loaded, then all health indicators (USB connection via WebHID, focus state, backend status) are displayed and updating.**
- **Given response metrics panel is visible, when viewing, then last 10-20 response times are displayed with min/max/average calculations.**
- **Given scans are processed, when metrics are collected, then latency and success/failure data are persisted to DB and queryable for later analysis.**
- **Given focus is on the scanner input field, when observing UI, then focus indicator shows active state visually (e.g., glowing border or icon).**
- **Given a ticket is scanned successfully, when the operator screen updates, then the current ticket number is displayed prominently in the UI.**
- **Given multiple tickets are scanned in sequence, when viewing the scan history panel, then the last 25 ticket numbers are shown with timestamps and status badges (success/duplicate/error).**
- **Given an operator clicks on a history item, when the detail view opens, then full scan metadata is shown including response time, Wix check-in status, and error details (if any).**
- **Given the session starts fresh, when the first scan occurs, then the history list begins populating and grows up to 25 items, then older items are removed as new ones are added.**

---

### Story P1-US-02b: Backend metrics schema and real-time health API
Status: `Done`

User story:
As an operator and system, I want structured metrics collection and a health API so scanner performance can be monitored and analyzed.

Tasks:
- [x] Design and implement ScanMetric database schema with fields: timestamp, session_id, operator_id, response_time_ms, latency_percentile, success_status, error_code, concurrent_count, scanner_status.
- [x] Create `/api/health/scanner` endpoint returning current backend connectivity, response time stats (last 100 requests), and system health.
- [x] Implement metrics middleware to intercept scan requests and log timing/status/concurrency.
- [x] Implement metrics aggregation service for real-time calculations (min/max/avg latency, success rate).
- [x] Add WebSocket endpoint `/ws/health` for real-time health status push if frontend requests live updates (fallback to polling endpoint).
- [x] Implement metrics cleanup/archival policy (e.g., keep high-detail metrics for 24h, aggregate for 30d).
- [x] Add metrics query endpoint `/api/metrics/scans` with filters (date_range, operator_id, session_id) for analysis.

Acceptance criteria:
- Given a scan request completes, when metrics middleware runs, then latency and status are recorded in ScanMetric table.
- Given `/api/health/scanner` is called, then response includes latency percentiles, success rate, and backend status (green/yellow/red).
- Given frontend polls health endpoint every 5 seconds, when response time is queried, then last 10-20 response times are available in payload.
- Given metrics are queried, when filters are applied, then results are aggregated correctly and queryable for performance analysis.
- Given WebSocket is enabled, when client subscribes to `/ws/health`, then real-time health updates are pushed to client without polling delay.

---

### Story P1-US-02c: Kiosk bootstrap QR and event-scoped station enrollment
Status: `Done`

User story:
As an operator, I want the kiosk to boot into a scan-ready landing page and accept a bootstrap QR so the station is bound to the correct event and shift without typing credentials.

Tasks:
- [x] Launch the app directly into a kiosk landing page with autofocus on the scan input.
- [x] Treat the first QR after boot as a bootstrap QR when no event is active.
- [x] Bind the kiosk session to `activeEventId`, `activeStationId`, and `bootstrapSessionId`.
- [x] Allow an explicit admin override path for switching events on a live kiosk.
- [x] Clear or expire the bootstrap session on timeout, reset, or manual sign-out.

Acceptance criteria:
- Given the kiosk restarts, when the app loads, then it lands on a scan-ready page with no manual login prompt.
- Given no event is active, when a valid bootstrap QR is scanned, then the kiosk binds to the correct event and station context.
- Given a bootstrap QR for a different event, when the kiosk already has an active event, then the scan is rejected or requires explicit admin override.
- Given the kiosk is already bound, when attendee QR scans arrive, then they are processed under the active event context.

---

### Story P1-US-03: QR parsing and check-in API contract
Status: `Not Started`

User story:
As the backend service, I want to parse QR payloads consistently so ticket identifiers can be validated and checked in.

Tasks:
- Define scan request/response schemas.
- Implement QR parsing service with support for known payload formats.
- Validate eventId/ticketNumber extraction and reject malformed payloads.
- Add idempotency key generation (`eventId + ticketNumber + blockId + operationType`).
- Return normalized status codes for frontend display.

Acceptance criteria:
- Given a valid QR payload, when `/api/checkins/scan` is called, then ticketNumber and event context are parsed correctly.
- Given malformed input, when parsing fails, then the API returns `INVALID_TICKET` with a clear error reason.
- Given repeated identical requests, when idempotency key matches, then backend returns consistent non-duplicative behavior.

---

### Story P1-US-04: Wix ticket check-in integration
Status: `Not Started`

User story:
As the system, I want to call Wix ticket check-in APIs so successful scans update Wix as source of truth.

Tasks:
- Implement Wix client service with timeout, retry, and jitter strategy.
- Integrate check-in endpoint call for valid scan requests.
- Map Wix responses to internal status model.
- Implement safe handling for Wix 4xx/5xx/rate-limit responses.
- Add correlation IDs for request tracing.

Acceptance criteria:
- Given a valid ticket and healthy Wix API, when check-in is submitted, then Wix is updated and API returns `CHECKED_IN`.
- Given Wix rate limit responses, when retries are attempted, then backoff is applied and failures are classified correctly.
- Given a ticket already checked in at source, when check-in is attempted, then API returns `ALREADY_CHECKED_IN`.

---

### Story P1-US-05: Redis offline queue and dedupe safeguards
Status: `Not Started`

User story:
As an operator, I want scans to continue during outages so check-ins are not lost.

Tasks:
- Implement Redis keys for processed set, pending marker, and pending queue.
- Implement atomic dedupe guard using transaction or Lua script.
- Keep a local cached ticket manifest for the active event so offline validation can still distinguish known tickets from malformed or unknown ones.
- Enqueue check-ins when Wix is unavailable.
- Build worker to retry queued check-ins with attempt metadata.
- Add dead-letter queue for terminal failures.

Acceptance criteria:
- Given Wix is unavailable, when a valid scan occurs, then API returns `QUEUED_OFFLINE` and item is persisted in Redis queue.
- Given duplicate scans for same event/ticket, when second scan arrives, then duplicate is detected and not enqueued twice.
- Given Wix is unavailable, when a valid ticket exists in the cached manifest, then the kiosk can still validate the ticket locally and queue the check-in for later reconciliation.
- Given connectivity returns, when worker runs, then queued check-ins sync and status transitions are recorded.

---

### Story P1-US-05b: Event ticket manifest sync and local validation cache
Status: `Not Started`

User story:
As the system, I want a local ticket manifest per event so the kiosk can validate tickets when Wix is temporarily unavailable.

Tasks:
- Add a sync job that imports the active event ticket roster from Wix into PostgreSQL and Redis.
- Track ticket state, last known sync time, and source revision for each cached ticket.
- Expose read APIs for ticket status lookups from the local cache.
- Mark cached ticket data as stale when the sync horizon is exceeded.
- Reconcile cached ticket state back to Wix after connectivity returns.

Acceptance criteria:
- Given a successful sync, when the local cache is refreshed, then the active event has a queryable ticket manifest.
- Given Wix is offline, when a known ticket is scanned, then the backend can validate against the cached manifest and continue operating.
- Given the cache is stale beyond the allowed threshold, when the operator opens the kiosk, then the UI warns that validation is degraded.
- Given connectivity returns, when the sync job runs, then the cached manifest is updated and reconciliation continues.

---

### Story P1-US-05c: Mobile app check-in webhook and real-time manifest updates
Status: `Not Started`

User story:
As the system, I want to receive real-time check-in events from Wix mobile app so the local ticket manifest stays synchronized and duplicate check-ins are prevented at the kiosk.

Tasks:
- Create webhook endpoint `POST /api/webhooks/wix/checkins` to receive mobile app check-in notifications from Wix.
- Define webhook payload schema: { ticket_number, wix_ticket_id, wix_event_id, checked_in_at, source: "wix_mobile", wix_request_id }.
- Implement webhook signature verification (Wix-signed header validation for security).
- When webhook is received:
  - Find the corresponding event by wix_event_id.
  - Look up ticket in event_ticket_manifest by ticket_number.
  - Update ticket manifest_state to `checked_in` and last_seen_scan_at to webhook timestamp.
  - Create scan_event record with source `wix_mobile` and result `checked_in`.
  - Create checkin_record with source tracking.
  - Emit event to kiosk operator (broadcast to all active sessions for this event).
- Add retry logic in Wix webhook delivery if your endpoint returns 5xx (Wix will retry automatically).
- Add webhook endpoint logging and audit trail.
- Provide UI admin panel to view webhook delivery history and manual webhook retry trigger.

Acceptance criteria:
- Given Wix mobile app checks in a ticket, when webhook is received, then local ticket manifest is immediately updated to checked_in.
- Given webhook signature verification fails, when webhook is received, then request is rejected with 401 Unauthorized.
- Given ticket is checked in via mobile app webhook, when operator scans the same ticket at kiosk, then kiosk detects `already_checked_in` state and displays duplicate message.
- Given webhook delivery fails due to temporary backend unavailability, when Wix retries, then eventual consistency is achieved and ticket is marked checked in.
- Given multiple mobile check-ins for same ticket arrive in rapid succession, when webhooks are processed, then only one check-in is recorded (dedupe by ticket_number per event).
- Given a webhook is received for an unknown event, when processed, then error is logged and webhook is acknowledged to Wix (to prevent retry spam).
- Given operator views webhook admin panel, when history is displayed, then recent webhook deliveries and their outcomes (success/failure/retry) are visible.

---

### Story P1-US-06: Credential provider abstraction (env/secrets manager/DB encrypted)
Status: `Not Started`

User story:
As a platform engineer, I want a credential abstraction layer so Wix auth can be sourced securely and rotated safely.

Tasks:
- Define credential provider interface.
- Implement environment-variable provider.
- Implement encrypted database provider scaffold.
- Implement provider selection via configuration.
- Ensure no secret values are logged.

Acceptance criteria:
- Given provider mode is `env`, when Wix client initializes, then credentials are loaded from environment settings.
- Given provider mode is `db`, when credentials exist in DB, then decrypted values are available only in memory during request execution.
- Given debug logging is enabled, when auth requests run, then secret values remain redacted.

---

### Story P1-US-07: Local edge relay service bootstrap
Status: `Not Started`

User story:
As an operator, I want a lightweight local relay in the venue so scans can be accepted over LAN even when internet is unstable.

Tasks:
- Create edge relay service (small FastAPI or Node service) runnable on a local mini PC/laptop.
- Expose local endpoint for station scan submissions.
- Add health endpoint and startup scripts for kiosk environments.
- Add secure relay authentication to cloud backend.
- Document local deployment requirements (OS, auto-start, network ports).

Acceptance criteria:
- Given local relay is running, when station submits a scan over LAN, then relay acknowledges the scan.
- Given cloud backend is reachable, when relay forwards scans, then backend receives them with relay metadata.
- Given relay restarts, when startup is configured, then relay auto-starts and serves traffic.

---

### Story P1-US-08: Edge relay durable local queue and forwarder
Status: `Not Started`

User story:
As an operator, I want the relay to keep scans locally during WAN outages so no check-ins are lost.

Tasks:
- Add local durable queue in relay (SQLite or embedded store).
- Persist queued scan events before acknowledgement to station.
- Implement forwarder loop with exponential backoff and jitter.
- Add dead-letter handling for unrecoverable relay-forward failures.
- Add replay-safe resend behavior.

Acceptance criteria:
- Given WAN outage, when station scans tickets, then relay stores events locally and returns accepted status.
- Given WAN recovery, when forwarder runs, then queued events are sent to cloud and marked synced.
- Given relay restart while offline, when service returns, then previously queued events are still available.

---

### Story P1-US-09: End-to-end duplicate prevention across relay and cloud
Status: `Not Started`

User story:
As a platform owner, I want strict duplicate protection across station, relay, backend, and Wix so each ticket is checked in once.

Tasks:
- Define immutable `scanEventId` generated at station (UUIDv7 suggested).
- Add relay idempotency ledger keyed by `scanEventId`.
- Add backend dedupe ledger keyed by (`eventId`, `ticketNumber`) and `scanEventId`.
- Enforce unique constraints in DB for dedupe records.
- Ensure worker and reconciliation paths are idempotent on repeated processing.

Acceptance criteria:
- Given the same scan event is submitted multiple times, when relay receives duplicates, then only one forward operation is performed.
- Given duplicate deliveries to backend, when dedupe checks run, then only one check-in side effect reaches Wix.
- Given concurrent scans of the same ticket from mobile app and relay path, when reconciliation completes, then final state is single checked-in ticket with deterministic outcome logging.

---

### Story P1-US-10: Relay-to-cloud contract and conflict semantics
Status: `Not Started`

User story:
As a developer, I want a clear relay/cloud protocol so delivery, retries, and conflict outcomes are predictable.

Tasks:
- Define relay payload schema including `scanEventId`, `relayId`, event context, and timestamps.
- Define acknowledgement schema with accepted, duplicate, invalid, and conflict outcomes.
- Add signed request verification between relay and cloud.
- Define conflict policy for pre-checked tickets and out-of-window scans.
- Add contract tests for protocol compatibility.

Acceptance criteria:
- Given valid relay payloads, when backend validates schema and signature, then request is accepted.
- Given malformed or unsigned payloads, when backend receives them, then requests are rejected with explicit reason.
- Given protocol version mismatch, when relay sends event, then compatibility behavior is deterministic and logged.

---

### Story P1-US-11: Wix site-event binding and app installation verification
Status: `Not Started`

User story:
As a platform administrator, I want clear site-event bindings and app installation verification so the system only uses events from approved Wix sites and prevents auth to wrong accounts.

Tasks:
- Add WixSiteEventBinding data model with fields: binding_id, wix_site_id, wix_event_id, app_installation_status (pending/verified/revoked), credential_profile_id, sync_policy_profile_id, binding_created_at, binding_verified_at, verified_by_actor.
- Implement backend endpoint `POST /api/admin/site-event-bindings` to create a binding.
- Add verification task: query Wix to confirm site exists, event exists, and app is installed on site.
- Store verification evidence with timestamp and actor.
- Prevent event activation if binding is unverified.
- Add UI screen to list, create, and view binding verification status.

Acceptance criteria:
- Given a new binding, when created, then initial status is pending.
- Given verification task runs, when binding details are confirmed in Wix, then status transitions to verified and timestamp is recorded.
- Given app is not installed on the site, when verification runs, then status remains pending and error reason is stored.
- Given an event is bound to a site, when event activation is attempted, then system checks binding status and rejects if not verified.
- Given a binding is verified, when querying events, then only events from verified bindings are available.

---

### Story P1-US-12: Wix app scope and permission verification
Status: `Not Started`

User story:
As a security administrator, I want to verify that the Wix app has the required OAuth scopes so the system can call check-in and ticket-read APIs without silent authorization failures.

Tasks:
- Define required OAuth scopes: `tickets:read`, `tickets.check-in:write`, `events:read` (and any other needed scopes).
- Add scope verification task: query Wix app installation to confirm scopes are present.
- Store scope audit record (scopes_verified_at, verified_scopes, missing_scopes).
- Add alert if required scopes are missing or revoked.
- Add scope re-verification endpoint callable from UI.
- Add UI indicator showing scope verification status on Integration Status screen.

Acceptance criteria:
- Given app installation is verified, when scope check runs, then required scopes are queried and compared.
- Given all required scopes are present, when verification completes, then status is green and no alerts fire.
- Given a required scope is missing, when verification completes, then missing scope is recorded and UI shows warning.
- Given scopes are re-verified, when task runs, then most recent verification result is stored.
- Given missing scopes are later granted, when re-verification is triggered, then status transitions to green.

---

### Story P1-US-13: Credential lifecycle and auth mode decision
Status: `Not Started`

User story:
As a platform engineer, I want explicit auth mode selection (OAuth vs API key) and a credential state machine so different environments can use different auth strategies safely.

Tasks:
- Add Auth Strategy configuration: define decision table showing which endpoints use which auth mode (check-in, ticket-read, event-read, sync).
- Define Credential lifecycle states: created, validated, active, expiring_soon, rotation_pending, revoked, failed.
- Add validation job: test credentials against Wix API before marking active.
- Implement state transitions: created -> validated -> active -> expiring_soon (automated on schedule) or -> rotation_pending (manual).
- Add backend configuration option to explicitly choose auth mode (OAuth or API Key) per environment.
- Add validation that production cannot mix modes for the same endpoint.
- Emit events for credential lifecycle transitions for audit and alerting.

Acceptance criteria:
- Given auth mode is selected, when documented, then decision rationale (production uses OAuth, staging can use API key) is recorded.
- Given a credential is created, when initial validation runs, then state transitions to validated if API calls succeed.
- Given a credential is active and approaching expiry, when TTL check runs, then state transitions to expiring_soon.
- Given expiring_soon credential, when refresh is attempted, then new credential is issued and old one is revoked.
- Given mixed mode configuration in production, when validation runs, then system rejects and blocks deployment.

---

### Story P1-US-14: Event readiness gate and pre-event validation
Status: `Not Started`

User story:
As an operator, I want an automated event readiness check before doors open so I know all dependencies are healthy.

Tasks:
- Add Event Readiness Check endpoint `GET /api/admin/events/{eventId}/readiness`.
- Readiness check includes:
  - Binding verified for event's site.
  - Credentials active and not expiring within 1 hour.
  - Scopes verified and complete.
  - Ticket manifest synced within last 30 seconds.
  - Local cache keys warmed in Redis.
  - Backend connectivity confirmed.
  - Worker service running and responsive.
- Return readiness status object: overall_status (ready/degraded/critical), component_statuses, failed_checks, recommended_actions.
- Add UI readiness dashboard shown during pre-event setup.
- Block event activation if readiness status is critical.
- Allow degraded status with operator acknowledgement.

Acceptance criteria:
- Given all dependencies are healthy, when readiness check runs, then overall_status is ready.
- Given credentials are expiring soon, when readiness check runs, then status is degraded and recommendation to refresh credentials is shown.
- Given ticket manifest is stale, when readiness check runs, then degraded status is returned.
- Given critical failures exist, when event activation is attempted, then system rejects with list of required fixes.
- Given operator acknowledges degraded status, when event activation proceeds, then status is logged for audit.

---

### Story P1-US-15: Reconciliation contract and drift semantics
Status: `Not Started`

User story:
As an architect, I want a clear reconciliation protocol so local check-in state can be safely merged with Wix as source of truth without data loss.

Tasks:
- Define Reconciliation State machine: in_sync, local_pending, local_only, wix_only, conflict.
- Define drift detection rules: query Wix for event's checked-in tickets, compare against local cache.
- Define resolution rules: deterministic tiebreaker (Wix wins on mismatches, but local pending items are retried).
- Implement reconciliation job that:
  - Fetches Wix checked-in tickets.
  - Compares against local cache.
  - Classifies each ticket into one of five states.
  - Generates reconciliation report with affected ticket counts and resolution actions taken.
- Add reconciliation conflict console: allow human review and manual override for edge cases.
- Add manual reconciliation trigger from UI.

Acceptance criteria:
- Given Wix and local state match, when reconciliation completes, then status is in_sync.
- Given local check-in is queued but Wix shows not checked in, when reconciliation runs, then ticket is retried.
- Given Wix shows checked in but local shows not checked in, when reconciliation runs, then local state is updated to match Wix.
- Given conflict state (both checked in at different times), when reconciliation runs, then deterministic outcome is logged and conflict console flags for review.
- Given operator manually resolves conflict, when override is applied, then both local state and audit log reflect resolution action and actor.

---

## Phase 2: Event Configuration and Credential Management

### Story P2-US-01: Event and block configuration CRUD
Status: `Not Started`

User story:
As an admin, I want to define events and blocks so check-in rules match event schedules.

Tasks:
- Build Event and Block Configuration screen.
- Add create/update/delete block operations.
- Implement validation for time ranges and overlap policies.
- Persist configurations with version metadata.
- Add backend APIs for retrieval and updates.

Acceptance criteria:
- Given valid block data, when admin saves configuration, then block is stored and retrievable.
- Given invalid time range (start >= end), when admin attempts save, then save is rejected with validation message.
- Given overlap disabled, when overlapping block is entered, then API rejects request.

---

### Story P2-US-02: Early check-in grace period rules
Status: `Not Started`

User story:
As an admin, I want grace periods per block so attendees can be checked in shortly before sessions start.

Tasks:
- Add grace period fields to block configuration.
- Implement block selection algorithm with deterministic tie-breaking.
- Add validation constraints for grace window bounds.
- Include selected block in check-in response payload.

Acceptance criteria:
- Given scan timestamp within `start - grace` and `end`, when check-in occurs, then ticket is assigned to the configured block.
- Given multiple eligible blocks, when selection executes, then deterministic priority is applied.
- Given invalid grace value, when admin saves, then save is blocked.

---

### Story P2-US-03: Batch reset and audit trail
Status: `Not Started`

User story:
As an admin, I want controlled reset actions so I can recover event state while preserving accountability.

Tasks:
- Implement reset endpoint for event-level and block-level scopes.
- Add confirmation workflow and reason capture in UI.
- Add RBAC guard for reset permissions.
- Persist audit entries for reset actions.

Acceptance criteria:
- Given authorized admin with confirmation, when reset is executed, then targeted check-in state is cleared.
- Given unauthorized user, when reset endpoint is called, then request is denied.
- Given any reset action, when completed, then audit record includes actor, timestamp, scope, and reason.

---

### Story P2-US-04: Wix synchronization controls screen
Status: `Not Started`

User story:
As an admin, I want to configure Wix sync behavior so local and Wix check-in data remain aligned.

Tasks:
- Build Wix Synchronization screen.
- Add enable/disable toggle and sync interval selector (1-2 min recommended).
- Display last successful sync, current lag, and last error.
- Persist sync settings per event.

Acceptance criteria:
- Given sync is enabled, when interval is saved, then worker schedules sync using configured cadence.
- Given sync is disabled, when saved, then scheduled sync jobs stop for the event.
- Given successful sync, when UI refreshes, then last-sync timestamp updates.

---

### Story P2-US-05: Authentication Settings screen (token mode)
Status: `Not Started`

User story:
As an admin, I want to view and control token-based authentication so Wix integration remains healthy.

Tasks:
- Build Authentication Settings screen.
- Show auth mode, token status, expiration, and last refresh time.
- Add manual refresh token action.
- Add test-connection action and result display.

Acceptance criteria:
- Given token mode is active, when screen loads, then token health metadata is shown without exposing token value.
- Given manual refresh is triggered, when refresh succeeds, then status and expiry are updated.
- Given connection test fails, when run from UI, then actionable error feedback is displayed.

---

### Story P2-US-06: API Key Management screen (API key mode)
Status: `Not Started`

User story:
As an admin, I want a secure UI to rotate API keys so account-level Wix operations can be managed safely.

Tasks:
- Build API Key Management screen with masked inputs.
- Add fields for API key and wix-account-id.
- Validate credentials before save via backend test endpoint.
- Record rotation metadata and audit event.

Acceptance criteria:
- Given valid API key/account ID, when admin saves, then backend stores encrypted values and returns success.
- Given invalid credentials, when validation runs, then save is rejected with clear guidance.
- Given successful rotation, when viewing history, then last-rotated metadata is visible.

---

### Story P2-US-07: Encrypted credential persistence in database
Status: `Not Started`

User story:
As a security owner, I want credentials encrypted at rest in DB so plaintext secrets are never persisted.

Tasks:
- Add credential tables for encrypted payload and metadata.
- Implement envelope encryption service with key versioning.
- Add rotate/re-encrypt operation for key changes.
- Add strict service-layer access control.

Acceptance criteria:
- Given a credential save request, when persisted, then DB stores encrypted blob and metadata only.
- Given unauthorized service path, when secret read is attempted, then access is denied.
- Given key rotation event, when re-encryption runs, then credentials remain readable by authorized services.

---

### Story P2-US-08: Secret rotation and audit screen
Status: `Not Started`

User story:
As a compliance admin, I want a dedicated rotation and audit screen so sensitive changes are traceable.

Tasks:
- Build Secret Rotation and Audit screen.
- Show credential actions log (create/update/test/rotate).
- Add rotate credential workflow with confirmation.
- Filter audit records by date, actor, action, and outcome.

Acceptance criteria:
- Given a rotation action, when completed, then a new audit record is visible immediately.
- Given filters are applied, when searching audit logs, then matching records are returned.
- Given non-admin user, when opening screen, then access is denied.

---

### Story P2-US-09: Edge relay management screen
Status: `Not Started`

User story:
As an admin, I want to manage venue relays/kiosks and generate bootstrap QR login credentials so each door team can quickly activate the correct event context.

Tasks:
- Build Edge Relay Management screen.
- Register relay instances with venue and station mapping.
- Show relay status, local queue depth, last heartbeat, and software version.
- Add controls to disable/enable a relay and rotate relay credentials.
- Add kiosk inventory view (edge and non-edge stations) with door assignment, active event, last bootstrap login, and operator/session metadata.
- Add bootstrap credential generator in admin UI:
  - Generate signed short-lived bootstrap payload tied to event + door/station scope.
  - Render QR preview for direct scanning on kiosk screen.
  - Provide copy-to-clipboard text output (signed token or signed short link) so admins can paste/share in chat tools with door leaders.
  - Support one-time-use and reusable-with-expiry modes.
- Add bootstrap credential lifecycle controls: revoke, regenerate, and audit trail.
- Add backend endpoint(s) for bootstrap token issuance and validation with signature verification and expiration checks.

Acceptance criteria:
- Given registered relay instances, when screen loads, then each relay shows current health and queue depth.
- Given relay credentials are rotated, when new credentials are issued, then old credentials are invalidated after grace window.
- Given relay heartbeat is stale, when threshold is exceeded, then UI indicates degraded relay state.
- Given an admin generates a bootstrap credential, when the QR is scanned on a kiosk, then the kiosk is logged into the assigned event/station scope.
- Given an admin uses copy/share output, when the door leader pastes the token/link in chat and opens it on a kiosk, then bootstrap login works without manual credential typing.
- Given a bootstrap credential is expired, revoked, or out-of-scope, when used by kiosk, then login is denied with explicit reason and an audit record is created.

---

## Phase 3: Metrics, Monitoring, and Reconciliation Visibility

### Story P3-US-01: Metrics and health dashboard implementation
Status: `Not Started`

User story:
As operations staff, I want live metrics so I can monitor event check-in performance.

Tasks:
- Build Metrics and Health Dashboard screen.
- Expose backend metrics summary endpoint.
- Add cards/charts for totals, per-event counts, per-block counts, and throughput.
- Add queue depth and sync lag visualization.

Acceptance criteria:
- Given active event traffic, when dashboard loads, then metrics update within expected refresh interval.
- Given queued offline items, when queue depth changes, then dashboard reflects updated values.
- Given no data available, when screen loads, then empty states are shown without errors.

---

### Story P3-US-02: Auth and token observability metrics
Status: `Not Started`

User story:
As a platform operator, I want credential health metrics so I can prevent integration outages.

Tasks:
- Add metrics for token expiry horizon, refresh success rate, auth failures, and credential validation failures.
- Add alert thresholds and UI badges.
- Expose dedicated auth health endpoint for monitoring tools.

Acceptance criteria:
- Given token nearing expiry threshold, when dashboard refreshes, then warning state is shown.
- Given repeated auth failures, when threshold is crossed, then alert is triggered.
- Given successful refresh, when metric pipeline updates, then failure counters do not increment.

---

### Story P3-US-03: Reconciliation visibility and drift detection
Status: `Not Started`

User story:
As an admin, I want reconciliation reporting so differences between local state and Wix can be resolved quickly.

Tasks:
- Implement reconciliation job summary model.
- Track drift count, affected tickets, and resolution outcomes.
- Add reconciliation panel to dashboard with last run details.
- Add operator action to re-run reconciliation on demand.

Acceptance criteria:
- Given detected drift, when reconciliation completes, then drift summary includes counts and impacted records.
- Given no drift, when reconciliation runs, then status is reported as healthy.
- Given manual re-run action, when requested, then new reconciliation run is initiated and tracked.

---

### Story P3-US-04: Alerting and operational notifications
Status: `Not Started`

User story:
As operations staff, I want proactive alerts so incidents are handled before check-in lines are impacted.

Tasks:
- Define alert rules for sync lag, queue growth, auth failures, and worker failures.
- Integrate notification channels (email, webhook, or chatops).
- Add dashboard alert center with active/resolved states.

Acceptance criteria:
- Given sync lag exceeds threshold, when condition persists, then an alert is emitted.
- Given issue recovery, when condition clears, then alert transitions to resolved.
- Given repeated failures, when deduplication window applies, then duplicate alerts are suppressed.

---

### Story P3-US-05: Edge relay observability and duplicate anomaly detection
Status: `Not Started`

User story:
As operations staff, I want relay-level metrics and duplicate anomaly alerts so local issues are detected before check-in lines are impacted.

Tasks:
- Add metrics for relay ingest rate, relay queue age, forward success rate, and replay counts.
- Add duplicate anomaly metrics (`duplicateScanEventId`, ticket collision rate).
- Add alert rules for stale relay heartbeat, queue growth, and duplicate spikes.
- Add relay drill-down panel in dashboard.

Acceptance criteria:
- Given relay queue age exceeds threshold, when condition persists, then an alert is emitted.
- Given duplicate anomaly spike, when detected, then dashboard and alert channel show affected venue/relay.
- Given normal operations, when dashboard is viewed, then relay metrics update in near real-time.

---

## Phase 4: Hardening, Security, and Production Readiness

### Story P4-US-01: RBAC and permission boundaries
Status: `Not Started`

User story:
As a security administrator, I want role-based controls so only authorized users can access sensitive actions.

Tasks:
- Define roles for operator, admin, and security admin.
- Enforce endpoint-level authorization in backend.
- Enforce UI route guards and action-level permissions.
- Add negative test coverage for restricted operations.

Acceptance criteria:
- Given operator role, when accessing credential screens, then access is denied.
- Given admin role, when accessing event config features, then access is granted.
- Given security admin role, when rotating secrets, then action succeeds and is audited.

---

### Story P4-US-02: Secret lifecycle runbook and operational policies
Status: `Not Started`

User story:
As an operations lead, I want documented lifecycle procedures so secret rotation and incident handling are repeatable.

Tasks:
- Create runbook for credential rotation, rollback, and validation.
- Define rotation cadence and emergency rotation flow.
- Define incident response for auth outage scenarios.
- Add pre/post-rotation verification checklist.

Acceptance criteria:
- Given planned rotation, when runbook is followed, then no downtime is introduced.
- Given failed rotation, when rollback procedure is executed, then service is restored.
- Given audit review, when checking records, then all lifecycle steps are traceable.

---

### Story P4-US-03: KMS-backed encryption migration (optional)
Status: `Not Started`

User story:
As a platform engineer, I want KMS-backed key management so encryption controls meet production standards.

Tasks:
- Integrate KMS key provider.
- Support key version metadata in credential records.
- Migrate existing encrypted credentials to KMS-managed keys.
- Add fallback behavior and failure handling.

Acceptance criteria:
- Given KMS is enabled, when credentials are stored, then envelope encryption uses KMS-wrapped data keys.
- Given migration runs, when completed, then all target credentials are re-encrypted and readable.
- Given KMS outage, when write attempts occur, then failures are explicit and do not corrupt existing secrets.

---

### Story P4-US-04: Full test matrix and release readiness gates
Status: `Not Started`

User story:
As a release manager, I want objective quality gates so production rollout is low-risk.

Tasks:
- Implement test suites: unit, integration, e2e, load, and resilience.
- Add CI gates for lint, tests, and security checks.
- Add staging sign-off checklist including scanner validation and Wix sync verification.
- Add go-live rollback plan.

Acceptance criteria:
- Given a release candidate, when CI runs, then all required quality gates pass.
- Given staging validation, when test checklist completes, then release receives sign-off.
- Given post-deploy issue, when rollback is triggered, then system returns to prior stable version.

---

### Story P4-US-05: Multi-relay resilience and failover drills
Status: `Not Started`

User story:
As an operations lead, I want verified failover procedures for local relays so venue operations remain stable during device/network failures.

Tasks:
- Define relay failover runbook (hot spare relay or rapid device swap).
- Simulate WAN outage + relay crash + restart scenarios.
- Validate no duplicate check-ins during replay after recovery.
- Capture mean recovery time and operational playbook updates.

Acceptance criteria:
- Given relay failure during event, when failover is executed, then scan intake is restored within target recovery time.
- Given outage recovery replay, when queued events are flushed, then duplicate protection remains intact.
- Given drill completion, when reviewed, then runbook includes validated steps and timings.

---

## Phase 4B: Wix Integration Verification and Live Event Drills

### Story P4B-US-01: Wix MCP integration verification script
Status: `Not Started`

User story:
As a release manager, I want a repeatable verification script using Wix MCP so each environment's integration is formally validated before event day.

Tasks:
- Create integration verification script (Python + Wix MCP or curl-based) with the following checks:
  - List Wix sites and confirm target site is present.
  - Query Wix app installation and confirm status.
  - Validate app scopes against required list.
  - Query Wix event and confirm event exists and is in expected state.
  - Perform read-only ticket query (non-mutating) to confirm API access.
  - Perform a dry-run check-in call (with idempotency key to ensure no side effect).
  - Capture all responses and format as verification report.
- Save report artifact in timestamped log.
- Make this script runnable in dev/staging/prod-like environments.
- Return zero exit code only if all checks pass.
- Add script to CI/CD and staging release gates.

Acceptance criteria:
- Given the script runs in dev environment, when all dependencies are healthy, then exit code is 0 and report shows green.
- Given an API key is invalid, when the script runs, then first auth failure is detected and reported with actionable error.
- Given scopes are missing, when the script runs, then missing scope is clearly listed in report.
- Given the script is called in CI before release, when any check fails, then release is blocked.

---

### Story P4B-US-02: Pre-event runbook and checklist
Status: `Not Started`

User story:
As an operations lead, I want a documented checklist so pre-event setup is repeatable and covers all Wix integration steps.

Tasks:
- Create Pre-Event Operations Runbook including:
  - 1 week before: verify credentials expiry, run integration verification script, confirm scopes.
  - 3 days before: dry-run full event readiness check, confirm ticket manifest sync interval.
  - 1 day before: run event readiness gate, confirm backend is responding, warm Redis cache.
  - 2 hours before: final readiness check, confirm relay (if used) is healthy, confirm operator can scan test ticket.
  - During event: monitor sync lag and queue depth, alert if > thresholds, keep runbook open.
  - Post-event: reconciliation audit, credential rotation if any were exposed, save logs for analysis.
- Add pre-event form in UI with checklist items operator can tick off.
- Add automatic email reminder for pre-event tasks (1 week, 3 days, 1 day before event).

Acceptance criteria:
- Given pre-event checklist is followed, when event begins, then all systems are confirmed ready.
- Given credential expiry warning is generated, when followed, then credential is rotated before expiry.
- Given event readiness check fails, when operator observes runbook, then recommended actions are clear.

---

### Story P4B-US-03: Live event drill: network outage + relay restart + reconciliation
Status: `Not Started`

User story:
As a resilience architect, I want a verified drill scenario so we know the system recovers correctly from realistic failure modes.

Tasks:
- Plan and execute multi-stage drill on staging event:
  - Stage 1 (network outage): Simulate WAN unavailability for 5 min, confirm scans are queued locally and relay buffers them.
  - Stage 2 (relay restart): Restart relay service during outage, confirm no queued items are lost.
  - Stage 3 (recovery and replay): Restore WAN, confirm relay replays queued check-ins to cloud without duplicates.
  - Stage 4 (reconciliation): Run reconciliation job and confirm final state matches Wix.
- Measure Mean Time To Recovery (MTTR) and document.
- Generate drill report with findings and any process improvements.
- Simulate parallel mobile app check-ins during recovery to test concurrent scenario.

Acceptance criteria:
- Given outage of 5 min with relay restart, when recovery executes, then all queued check-ins are processed.
- Given parallel mobile + relay check-ins during recovery, when reconciliation completes, then no duplicate check-ins exist in Wix.
- Given drill is completed, when report is reviewed, then MTTR is documented and acceptable (<10 min recommended).

---

### Story P4B-US-04: Credential rotation operational drill
Status: `Not Started`

User story:
As a security operations lead, I want a verified credential rotation procedure so rotations can be done under pressure without errors.

Tasks:
- Plan and execute credential rotation drill during event (staging):
  - Step 1: Generate new credential on Railway backend (env var update or DB change).
  - Step 2: Confirm old credential is still active and traffic continues.
  - Step 3: Warm new credential (make test request).
  - Step 4: Switch active credential (atomic update).
  - Step 5: Confirm traffic flows with new credential.
  - Step 6: Monitor for auth errors for 5 min.
  - Step 7: Revoke old credential.
- Measure downtime (should be near zero).
- Document any issues and rollback procedure.

Acceptance criteria:
- Given credential rotation is executed, when completed, then no check-in requests are dropped.
- Given old credential is revoked, when auth attempts are made with old key, then requests are rejected.
- Given rotation drill is completed, when reviewed, then downtime is < 1 minute (ideally zero).

---

### Story P4B-US-05: Operator incident response training
Status: `Not Started`

User story:
As a venue operations manager, I want a training runbook so on-site operators know how to handle common incidents.

Tasks:
- Create Operator Incident Response Guide covering:
  - "Scanner not detected": check USB connection, reload page, restart browser.
  - "Backend is down": scan state is queued offline, relay (if present) buffers, wait for recovery.
  - "Duplicate prevented": operator sees error, scan is not repeated, no action needed.
  - "Wix API timeout": backend queues request, operator sees "queued offline", check-in continues later.
  - "Relay heartbeat is stale": relay is degraded, all scans go directly to cloud if internet available.
  - "Get full readiness report": UI displays readiness dashboard, operator notes any yellow/red items.
  - "Manual override for pre-checked ticket": deny and explain duplicate prevention, escalate to manager if needed.
- Add quick-reference cards (1-page summaries) for top incidents.
- Conduct operator training session before go-live.

Acceptance criteria:
- Given operator training is completed, when incidents occur, then operator can handle without panic.
- Given reference cards are available on kiosk desk, when incident happens, then operator has procedural guidance.

---

## Cross-Cutting Technical Tasks (Apply in All Phases)

### X-US-01: Structured logging and traceability
Status: `Not Started`

Tasks:
- Add correlation ID propagation frontend -> backend -> worker -> Wix calls.
- Standardize structured logs with eventId, ticketNumber hash, outcome, and latency.

Acceptance criteria:
- Given a single scan request, when tracing logs, then all related operations can be correlated end to end.

---

### X-US-02: Security redaction and data handling
Status: `Not Started`

Tasks:
- Add log redaction middleware for secrets and PII.
- Add static checks to prevent secret logging regressions.

Acceptance criteria:
- Given auth operations run, when logs are inspected, then secrets are never present in plaintext.

---

## Delivery Sequence (Recommended)

1. P1-US-01
2. P1-US-02
3. P1-US-02b
4. P1-US-03
5. P1-US-04
6. P1-US-05
7. **P1-US-05b (NEW: Ticket manifest sync)**
8. **P1-US-05c (NEW: Mobile app webhook)**
9. P1-US-06
10. P1-US-07
11. P1-US-08
12. P1-US-09
13. P1-US-10
14. **P1-US-11 (NEW: Wix site-event binding)**
15. **P1-US-12 (NEW: Wix app scope verification)**
16. **P1-US-13 (NEW: Credential lifecycle & auth mode)**
17. **P1-US-14 (NEW: Event readiness gate)**
18. **P1-US-15 (NEW: Reconciliation contract)**
19. P2-US-01
20. P2-US-02
21. P2-US-04
22. P2-US-05
23. P2-US-06
24. P2-US-07
25. P2-US-08
26. P2-US-09
27. P2-US-03
28. P3-US-01
29. P3-US-02
30. P3-US-03
31. P3-US-04
32. P3-US-05
33. P4-US-01
34. P4-US-02
35. P4-US-03
36. P4-US-04
37. P4-US-05
38. **P4B-US-01 (NEW: Wix MCP verification script)**
39. **P4B-US-02 (NEW: Pre-event runbook)**
40. **P4B-US-03 (NEW: Live event drill)**
41. **P4B-US-04 (NEW: Credential rotation drill)**
42. **P4B-US-05 (NEW: Operator incident training)**
43. X-US-01 and X-US-02 continuously

## Definition of Done (Global)

A story is Done only when:

- All tasks are completed.
- All acceptance criteria are verified.
- Relevant automated tests are added and passing.
- Security and logging requirements are met.
- Documentation is updated (including operational notes where applicable).

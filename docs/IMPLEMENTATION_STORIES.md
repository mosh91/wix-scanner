# Wix Scanner Implementation Stories

This document turns the project plan into sequential user stories with concrete tasks and acceptance criteria.

## How to Use This File

1. Implement stories in the listed order.
2. Do not start a dependent story until blocking stories are complete.
3. Mark each story as Done only when all acceptance criteria pass.
4. Link each story to code PRs, tests, and runbook updates.

## Story Status Legend

- `Not Started`
- `In Progress`
- `Blocked`
- `Done`

---

## Phase 1: Core Functionality and MVP

### Story P1-US-01: Bootstrap backend and frontend foundations
Status: `Not Started`

User story:
As a developer, I want a working FastAPI + React project skeleton so we can build features quickly.

Tasks:
- Create backend project with FastAPI app, routing module, settings module, and health endpoint.
- Create frontend project with React app shell and route placeholders.
- Add shared environment configuration templates for backend and frontend.
- Add local developer scripts for run, test, lint, and format.
- Add Docker Compose baseline for backend, frontend, and Redis.
- Set up i18n framework (e.g., i18next or react-i18next) with Spanish as default language.
- Create base translation files structure (en.json, es.json) with common UI strings.
- Configure language detection and locale preference storage.

Acceptance criteria:
- Given a fresh clone, when I run the documented startup steps, then backend, frontend, and Redis start successfully.
- Given the backend is running, when I request `/api/health`, then I receive HTTP 200 with service status.
- Given the frontend is running, when I open the app, then the base layout and navigation render without errors.
- Given the app loads, when checking browser console, then app initializes with Spanish as default language.
- Given UI strings exist, when viewed in app, then Spanish translations are displayed for all static content.

---

### Story P1-US-02: HID scanner capture on operator screen
Status: `Not Started`

User story:
As a check-in operator, I want scanner input captured reliably so I can scan tickets quickly without manual typing.

Tasks:
- Build Operator Check-In screen with hidden focused input.
- Implement scan buffer with terminator key handling (default Enter).
- Add configurable debounce and max payload length validation.
- Add scan result feedback states (success, duplicate, invalid, queued, error).
- Add focus watchdog to recover scanner input capture if focus is lost.
- **Implement WebHID API integration for scanner detection and health**:
  - Use WebHID API to enumerate and detect connected USB HID scanner devices.
  - Request user permission to access scanner device on first use (browser security model).
  - Monitor device connection/disconnection events in real-time.
  - Implement device health check: send test request to scanner to verify responsiveness.
  - Handle graceful fallback if WebHID is unavailable (keyboard input as fallback).
  - Store permitted device IDs in browser storage for seamless reconnection.
- **Add real-time health status indicators to scanner screen**:
  - Scanner USB connection status via WebHID (connected/disconnected badge with vendor/model info if available)
  - Scanner device health indicator (responding/unresponsive based on device comms)
  - Input focus state indicator (visual feedback showing focus is active)
  - Backend connectivity status (green/yellow/red indicator with last check timestamp)
  - WebSocket connection status (if applicable, showing real-time sync state)
- **Implement response metrics display**:
  - Current response time display (last request latency in ms)
  - Response time history (last 10-20 responses with min/max/average)
  - Success/error rate indicator (e.g., "98% success last hour")
- **Add metrics collection service**:
  - Collect response time, timestamp, success/failure status for each scan
  - Track concurrent request count
  - Persist scan metrics to backend DB for later analysis
  - Include scanner session metadata (session ID, operator info)
 - **Display current and recent scan history**:
   - Show prominently the current/last scanned ticket number on the operator screen.
   - Maintain and display a rolling list of the last 25 scanned ticket numbers with status (success/error/duplicate).
   - Include timestamps and result status for each recent ticket in the history list.
   - Allow operator to click history items to view detailed scan info (response time, Wix status, etc.).

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
Status: `Not Started`

User story:
As an operator and system, I want structured metrics collection and a health API so scanner performance can be monitored and analyzed.

Tasks:
- Design and implement ScanMetric database schema with fields: timestamp, session_id, operator_id, response_time_ms, latency_percentile, success_status, error_code, concurrent_count, scanner_status.
- Create `/api/health/scanner` endpoint returning current backend connectivity, response time stats (last 100 requests), and system health.
- Implement metrics middleware to intercept scan requests and log timing/status/concurrency.
- Implement metrics aggregation service for real-time calculations (min/max/avg latency, success rate).
- Add WebSocket endpoint `/ws/health` for real-time health status push if frontend requests live updates (fallback to polling endpoint).
- Implement metrics cleanup/archival policy (e.g., keep high-detail metrics for 24h, aggregate for 30d).
- Add metrics query endpoint `/api/metrics/scans` with filters (date_range, operator_id, session_id) for analysis.

Acceptance criteria:
- Given a scan request completes, when metrics middleware runs, then latency and status are recorded in ScanMetric table.
- Given `/api/health/scanner` is called, then response includes latency percentiles, success rate, and backend status (green/yellow/red).
- Given frontend polls health endpoint every 5 seconds, when response time is queried, then last 10-20 response times are available in payload.
- Given metrics are queried, when filters are applied, then results are aggregated correctly and queryable for performance analysis.
- Given WebSocket is enabled, when client subscribes to `/ws/health`, then real-time health updates are pushed to client without polling delay.

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
- Enqueue check-ins when Wix is unavailable.
- Build worker to retry queued check-ins with attempt metadata.
- Add dead-letter queue for terminal failures.

Acceptance criteria:
- Given Wix is unavailable, when a valid scan occurs, then API returns `QUEUED_OFFLINE` and item is persisted in Redis queue.
- Given duplicate scans for same event/ticket, when second scan arrives, then duplicate is detected and not enqueued twice.
- Given connectivity returns, when worker runs, then queued check-ins sync and status transitions are recorded.

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
As an admin, I want to manage venue relays so I can monitor local ingestion reliability per location.

Tasks:
- Build Edge Relay Management screen.
- Register relay instances with venue and station mapping.
- Show relay status, local queue depth, last heartbeat, and software version.
- Add controls to disable/enable a relay and rotate relay credentials.

Acceptance criteria:
- Given registered relay instances, when screen loads, then each relay shows current health and queue depth.
- Given relay credentials are rotated, when new credentials are issued, then old credentials are invalidated after grace window.
- Given relay heartbeat is stale, when threshold is exceeded, then UI indicates degraded relay state.

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
7. P1-US-06
8. P1-US-07
9. P1-US-08
10. P1-US-09
11. P1-US-10
12. P2-US-01
13. P2-US-02
14. P2-US-04
15. P2-US-05
16. P2-US-06
17. P2-US-07
18. P2-US-08
19. P2-US-09
20. P2-US-03
21. P3-US-01
22. P3-US-02
23. P3-US-03
24. P3-US-04
25. P3-US-05
26. P4-US-01
27. P4-US-02
28. P4-US-03
29. P4-US-04
30. P4-US-05
31. X-US-01 and X-US-02 continuously

## Definition of Done (Global)

A story is Done only when:

- All tasks are completed.
- All acceptance criteria are verified.
- Relevant automated tests are added and passing.
- Security and logging requirements are met.
- Documentation is updated (including operational notes where applicable).

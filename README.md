# Wix Event QR Check-In System

## Project Description

This project provides a robust QR code-based event check-in platform for Wix-managed events.

Attendees present a QR code ticket, a USB 2D scanner (HID keyboard mode) reads the code, and the system validates and checks the ticket in through Wix APIs. The platform is designed to operate reliably in real venue conditions where internet connectivity may be unstable.

Core goals:

- Fast, low-friction check-in flow at entry points.
- Reliable operation during intermittent network outages.
- Strong duplicate check-in prevention, even across retries and reconnections.
- Operational visibility through metrics and health dashboards.
- Scalable architecture that supports multiple devices and check-in stations.

## Objectives and Non-Goals

### Objectives

- Integrate QR scanning with Wix Events ticket check-in.
- Maintain an offline-capable queue for pending check-ins.
- Prevent duplicate check-ins with idempotent processing.
- Provide event/block configuration and administrative tools.
- Provide real-time and historical check-in metrics.

### Non-Goals (Initial Scope)

- Replacing Wix as source of truth for ticket ownership.
- Building a custom mobile scanner app (scanner is HID keyboard mode).
- Full BI platform beyond operational dashboards.

## Technology Stack

- Backend API: Python + FastAPI
- Frontend: React
- Cache / Queue / Fast state: Redis
- External integration: Wix Events API
- Optional worker: Python background worker process (can be in same service initially)

## High-Level Architecture

1. Scanner input is captured in the React app via a focused input listener.
2. React sends scanned payload to FastAPI (`/scan` or `/checkins`).
3. FastAPI parses QR payload and extracts `ticketNumber` and event metadata.
4. FastAPI runs duplicate and eligibility checks against Redis and Wix.
5. If online and valid, FastAPI calls Wix check-in endpoint and records local state.
6. If Wix is unreachable, FastAPI stores the request in Redis pending queue.
7. A sync worker retries pending queue items with backoff and idempotency safeguards.
8. Metrics are updated in Redis and exposed to dashboard endpoints.

## Component Design

### 1) Frontend (React)

Responsibilities:

- Capture scanner data from HID keyboard stream.
- Maintain focus-safe scan input mode for operator screens.
- Display immediate result states: success, duplicate, invalid, offline queued, error.
- Provide admin pages for event/block configuration.
- Show metrics dashboard and synchronization status.

Implementation notes:

- Use a hidden, always-focused input and key buffering with short debounce (for scanner burst input).
- Detect end-of-scan with terminator key (typically Enter) configurable per scanner model.
- Add audible/visual feedback with latency target under 250 ms for local response.

### 2) Backend API (FastAPI)

Responsibilities:

- Expose REST endpoints for scan/check-in/config/metrics/ops.
- Parse and validate QR payloads.
- Enforce idempotent check-in and duplicate prevention.
- Communicate with Wix APIs and handle retries/backoff.
- Write/read Redis for queueing, cache, dedupe sets, and metrics.

Suggested endpoint surface:

- `POST /api/checkins/scan`: submit raw scan data.
- `POST /api/checkins/manual`: admin manual override check-in.
- `GET /api/checkins/status/{ticketNumber}`: fetch check-in status.
- `GET /api/events`: list configured events.
- `POST /api/events/{eventId}/blocks`: configure blocks.
- `POST /api/events/{eventId}/reset`: clear check-ins (audited).
- `GET /api/metrics/summary`: aggregate totals.
- `GET /api/health`: health/readiness.

### 3) Redis (Caching + Queue + Real-Time State)

Responsibilities:

- Offline pending queue for unsent check-ins.
- Deduplication keys for idempotency and duplicate prevention.
- Event/block configuration cache for low-latency reads.
- Aggregated counters and time buckets for dashboard metrics.

Suggested Redis data model:

- `checkin:processed:{eventId}` (Set): ticket numbers successfully processed locally.
- `checkin:request:{idempotencyKey}` (String/Hash + TTL): request fingerprint.
- `checkin:pending` (Stream or List): queued offline check-ins.
- `checkin:pending:byTicket:{eventId}:{ticketNumber}` (String): pending marker.
- `event:{eventId}:config` (Hash/JSON): event-level config.
- `event:{eventId}:blocks` (Sorted Set or JSON): time blocks + grace period.
- `metrics:event:{eventId}:count` (Counter): total check-ins.
- `metrics:event:{eventId}:block:{blockId}:count` (Counter).
- `metrics:timeseries:{eventId}:{YYYYMMDDHHmm}` (Counter).

### 4) Wix Integration Layer

Responsibilities:

- Validate ticket context with Wix where required.
- Perform check-in via Wix check-in endpoint.
- Normalize Wix responses into internal status model.
- Implement retry with exponential backoff + jitter.

Important considerations:

- Respect Wix API rate limits with token bucket/leaky bucket strategy.
- Use request timeouts and circuit breaker behavior to fail fast.
- Secure credentials via environment variables and secret management.

### 5) Background Sync Worker

Responsibilities:

- Poll/consume pending queue from Redis.
- Retry submissions when connectivity resumes.
- Preserve ordering where required per event/ticket.
- Record terminal outcomes (synced, duplicate-at-source, invalid, failed).

Reliability pattern:

- At-least-once queue processing + idempotent check-in operation.
- Dead-letter queue (DLQ) for repeatedly failing items.
- Operator tools to inspect/retry DLQ items.

## End-to-End Check-In Flow

### Online Flow

1. Scanner sends QR text to frontend.
2. Frontend posts payload to backend.
3. Backend parses ticket number and computes idempotency key.
4. Backend checks Redis dedupe keys.
5. If not duplicate, backend calls Wix check-in API.
6. On success, backend marks ticket as checked-in in Redis and updates metrics.
7. Frontend receives success response with timestamp and source (`wix-online`).

### Offline/Degraded Flow

1. Scan request reaches backend, Wix is unavailable or timed out.
2. Backend performs local dedupe check.
3. Backend stores check-in in Redis pending queue with durable metadata.
4. Backend returns `queued-offline` status immediately.
5. Worker retries queued entries later.
6. On successful sync, worker updates status and metrics.

## Duplicate Check-In Prevention Strategy

Use a layered approach to guarantee practical exactly-once behavior:

1. Request idempotency key:
	 - Key suggestion: `hash(eventId + ticketNumber + blockId + operationType)`.
2. Fast local guard in Redis:
	 - Reject if `checkin:processed:{eventId}` already contains `ticketNumber`.
3. Pending guard:
	 - Reject or coalesce if pending marker already exists for same ticket/event.
4. Source-of-truth reconciliation:
	 - If ambiguity exists, query Wix ticket status before final decision.
5. Atomic writes:
	 - Use Redis transactions/Lua scripts for check-and-set operations.

Recommended response statuses:

- `CHECKED_IN`
- `ALREADY_CHECKED_IN`
- `QUEUED_OFFLINE`
- `INVALID_TICKET`
- `OUTSIDE_BLOCK_WINDOW`
- `ERROR`

## Event and Block Configuration

Admin users can configure:

- Event identity (Wix event mapping).
- Block definitions (`blockId`, name, start/end).
- Early check-in grace window (minutes before block start).
- Optional overlap policy between blocks.
- Reset permissions and confirmation requirements.

Validation rules:

- Start time < end time.
- No unintended overlaps unless explicitly allowed.
- Grace period bounded (for example 0-120 min).
- All configs versioned and audit logged.

Early check-in logic:

- If scan time is within `start - gracePeriod` to `end`, assign check-in to that block.
- If multiple blocks qualify, apply deterministic priority (nearest start time).

Batch reset behavior:

- Reset by event or specific block.
- Requires elevated role + confirmation.
- Write audit trail with actor, time, scope, and reason.

## Wix Synchronization for Check In by Wix Mobile App

This section explains how to configure database synchronization with Wix so your local HID scanner workflow and the Check In by Wix mobile app can run in parallel.

### Configuration Steps

1. Enable Wix synchronization:
	- Open the Event Configuration screen in the admin UI.
	- Find the Wix Synchronization toggle and set it to enabled.
	- Save the configuration so scheduled synchronization starts.

2. Set synchronization frequency:
	- Configure the sync interval in the same Event Configuration area.
	- Recommended interval: 1 to 2 minutes for near real-time consistency.
	- Use 1 minute for high-traffic events and 2 minutes for lower traffic.

3. Enable parallel scanner operation:
	- Keep local HID scanner check-in enabled in the operator UI.
	- Confirm the event is also accessible in the Check In by Wix mobile app.
	- Verify both flows write to and read from Wix as shared source-of-truth for check-in state.

### Operational Notes

- Active internet connectivity is required for synchronization between this system and Wix.
- The Check In by Wix app must be installed on a mobile device and linked to the correct Wix account.
- After synchronization, check-in updates are reflected in both systems, enabling concurrent scanning from desktop HID stations and mobile devices.

### Reliability Recommendations for Sync Mode

- Keep idempotency and duplicate-prevention checks active locally even when sync is enabled.
- During temporary outages, queue local check-ins and sync them on reconnect.
- Run a periodic reconciliation job (for example every 5 to 15 minutes) to resolve drift between local state and Wix.
- Alert operators when sync lag exceeds a defined threshold (for example 3 minutes).

## Metrics Dashboard

Provide near real-time operational metrics:

- Total check-ins (overall and per event).
- Check-ins per block.
- Current attendees.
- Check-in throughput (per minute).
- Queue depth and sync lag.
- Error rates by type (invalid, duplicate, API timeout).

Technical approach:

- Maintain counters in Redis for low-latency reads.
- Use rolling time buckets for trend charts.
- Optionally stream updates via WebSockets/SSE to frontend.

## Performance and Scalability Recommendations

- Keep check-in API stateless; scale horizontally with multiple FastAPI instances.
- Centralize shared state in Redis (single source for dedupe/queue/cache).
- Use connection pooling for Redis and HTTP clients.
- Apply backpressure when Wix is slow (queue-first mode).
- Use async I/O in FastAPI for Wix and Redis calls.
- Add per-endpoint and global rate limiting.
- Use structured logs and correlation IDs for scan request tracing.

Latency targets (suggested):

- Local API acknowledgement: p95 < 300 ms.
- Online Wix check-in round trip: p95 < 1500 ms.
- Offline queue enqueue: p95 < 200 ms.

## Reliability and Fault Tolerance

- Redis persistence: enable AOF (`appendfsync everysec`) for durable queue/state.
- Run Redis with replication + Sentinel/managed equivalent for high availability.
- Implement health checks:
	- Liveness: process health.
	- Readiness: Redis connectivity + Wix dependency state.
- Introduce circuit breaker for Wix failures.
- Retry policy: exponential backoff with jitter and max attempts.
- Dead-letter queue for non-recoverable or repeated failures.
- Regular backups for critical configs and audit records.

## Security Recommendations

- Store Wix credentials in environment variables or a secrets manager.
- Enforce RBAC for admin features (config/reset/manual override).
- Use signed JWT/OAuth for frontend-authenticated actions.
- Apply TLS in transit for all external/internal traffic.
- Sanitize and validate all scanner input (length, format, character set).
- Add audit logs for sensitive operations.

## Proposed Repository Structure

```text
.
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── services/
│   │   ├── models/
│   │   └── workers/
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   ├── hooks/
│   │   └── services/
│   └── package.json
├── infra/
│   ├── docker/
│   ├── redis/
│   └── monitoring/
└── README.md
```

## Plan Phases

### Phase 1: Core Functionality and MVP

Objective: establish core scan-to-check-in flow with offline queueing and dedupe.

Tasks:

- Bootstrap FastAPI and React projects.
- Implement HID scan capture and QR parsing pipeline.
- Integrate Wix check-in endpoint.
- Implement initial Wix pull/push synchronization service to keep local check-in state aligned with Wix.
- Add Redis-backed pending queue and processed-ticket set.
- Implement basic idempotency + duplicate prevention.
- Add baseline logging, health checks, and error handling.

Deliverables:

- Working check-in endpoint.
- Basic Wix synchronization running on a fixed schedule.
- Offline queue with retry worker.
- Operator UI showing scan outcomes.

### Phase 2: Event Configuration and Management

Objective: enable full event/block administration and policy controls.

Tasks:

- Build event/block admin screens.
- Persist and cache configurations in Redis.
- Add Event Configuration controls for Wix Synchronization enable/disable and sync interval (recommended 1 to 2 minutes).
- Implement grace period and block assignment rules.
- Implement event/block reset with audit logging.
- Harden validation and conflict handling.

Deliverables:

- Configurable event operations.
- Admin-managed Wix synchronization settings and validation.
- Safe reset tools with auditable actions.

### Phase 3: Metrics and Monitoring

Objective: provide visibility into operations and system health.

Tasks:

- Build dashboard for key operational metrics.
- Implement metrics aggregation endpoints.
- Add queue depth/sync lag/error analytics.
- Add synchronization health metrics for Wix parity (last successful sync time, drift count, and reconciliation results).
- Add alerting hooks for degraded service states.

Deliverables:

- Real-time dashboard.
- Basic observability with actionable alerts.

### Phase 4: Optimization, Security, and Deployment

Objective: production hardening, scalability, and secure rollout.

Tasks:

- Optimize Redis key design and memory usage.
- Add full authn/authz and permission boundaries.
- Expand test coverage (unit/integration/e2e/load/failure tests).
- Add CI/CD, deployment manifests, and runbooks.
- Conduct resilience drills and fix edge cases.

Deliverables:

- Production-ready deployment package.
- Security-reviewed and performance-validated release.

## Testing Strategy

- Unit tests: QR parser, block-window logic, dedupe logic.
- Integration tests: FastAPI + Redis + mocked Wix API.
- End-to-end tests: scanner-like input to UI and backend response.
- Chaos/failure tests: Wix outage, Redis failover, network partitions.
- Load tests: concurrent scan bursts and queue drain performance.

## Deployment Guidance

- Containerize backend, worker, and frontend.
- Deploy backend and worker as separate scalable services.
- Use managed Redis where possible for availability and backups.
- Configure environment-specific settings via env vars.
- Add dashboards and alerting before go-live.

## Operational Runbook Essentials

- How to identify queue growth and sync lag.
- How to inspect/retry dead-letter queue items.
- How to rotate Wix credentials safely.
- How to perform emergency fallback to queue-only mode.
- How to execute audited event/block reset.

## Risks and Mitigations

- Wix API rate limits or outages:
	- Mitigation: queue-first fallback, retries, circuit breaker, throttling.
- Scanner focus/input issues in browser:
	- Mitigation: persistent focus handler, kiosk mode, focus watchdog.
- Duplicate scans in high-throughput lines:
	- Mitigation: atomic dedupe keys + short cool-down window.
- Redis data loss risk:
	- Mitigation: AOF persistence, backups, replication, failover testing.

## Configuration and Secrets

Example environment variables:

- `WIX_API_BASE_URL`
- `WIX_API_KEY` or OAuth credentials
- `REDIS_URL`
- `CHECKIN_RETRY_MAX_ATTEMPTS`
- `CHECKIN_RETRY_BASE_MS`
- `DEFAULT_GRACE_PERIOD_MINUTES`
- `JWT_PUBLIC_KEY` / auth config

Never hardcode API keys or secrets in source code.

## Wix API Reference

Primary endpoint for ticket check-in:

- https://dev.wix.com/docs/api-reference/business-solutions/events/registration/ticketing/tickets/check-in-ticket

Use version-aware client wrappers to isolate future API changes.

## Suggested Next Implementation Step

Start with Phase 1 by implementing a vertical slice:

- Scan capture in React -> FastAPI `/api/checkins/scan` -> Redis dedupe -> Wix check-in -> response toast.

Then add offline queueing and sync worker as the next increment.

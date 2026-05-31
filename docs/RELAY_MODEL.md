# Relay Model (Edge Relay)

This document explains what the relay service is and when you should deploy it.

## Terminology

- Relay (not "rely") = local edge service under [relay](../relay) that can accept scans over LAN and forward to cloud.

## Is relay part of the server, or a standalone kiosk component?

## Short answer

- Relay is an optional edge component.
- It is separate from the cloud backend server process.
- You run it on a local venue machine only when you need LAN-first buffering/resilience.

## What problem relay solves

- Absorbs short-to-medium WAN outages while doors keep scanning.
- Reduces direct dependency between every kiosk and cloud backend reachability.
- Provides a local acceptance point over LAN and forwards safely when cloud is reachable again.

## Deployment model

- Without relay:
  - Kiosk browser talks directly to backend API.
  - Simpler setup, fewer moving parts.
  - Best when internet is stable.

- With relay:
  - Kiosk/stations can post scans to local relay.
  - Relay acknowledges quickly, queues locally if WAN is unstable, then forwards to backend.
  - Best for venues with poor or unstable internet.

## Topology options

- Direct mode (no relay):
  - Kiosk browser -> Backend API
- Relay mode:
  - Kiosk browser -> Relay API -> Backend API

Both modes use the same kiosk bootstrap flow. Relay changes transport/resilience behavior, not bootstrap token format.

## Where relay is implemented

- Service code: [relay/app](../relay/app)
- Deployment/runbook: [relay/DEPLOYMENT.md](../relay/DEPLOYMENT.md)
- Intro: [relay/README.md](../relay/README.md)
- Dev stack includes relay in [infra/wix_scanner/docker-compose.dev.yml](../infra/wix_scanner/docker-compose.dev.yml)

## Do you need relay for every kiosk?

- No.
- Use relay when any of these are true:
  - Venue WAN is unreliable.
  - You want local queuing independent of cloud reachability.
  - You need stronger continuity guarantees at doors during outages.

- Skip relay when:
  - Connectivity is stable and direct backend access is enough.
  - Operational simplicity is higher priority than edge resiliency.

## How to use relay (quick practical guide)

## 1) Start relay

Development with compose:

```bash
cd infra/wix_scanner
docker compose -f docker-compose.dev.yml up -d relay
```

Relay listens on port 9000 in local dev by default.

## 2) Configure relay -> backend trust

Ensure these shared settings are aligned between backend and relay environments:

- relay auth token
- relay signing secret
- relay protocol version

If these do not match, relay-to-cloud calls will be rejected.

## 3) Point kiosk/station traffic to relay

In relay mode, scanner submissions should target relay endpoint:

- POST /api/relay/scans

Relay then forwards to backend check-in endpoint using signed relay contract metadata.

## 4) Validate health before doors open

Check relay health:

```bash
curl -s http://localhost:9000/api/health
```

Check backend health separately:

```bash
curl -s http://localhost:8000/api/health
```

## 5) Observe queue behavior during outage tests

When WAN is degraded/unavailable:

- relay should keep acknowledging scans locally
- queue depth should rise

When WAN recovers:

- queued scans should drain
- duplicate protection remains enforced end-to-end

## Operating checklist per venue

- Decide mode per venue: direct or relay.
- If relay mode, deploy one relay per venue/LAN segment.
- Validate relay health and backend reachability before opening doors.
- Run at least one controlled outage drill in staging before production events.
- Keep relay and backend protocol/auth/signing settings synchronized after rotations.

## Recommended current architecture decision

- Start direct-to-backend for controlled pilots.
- Add relay per venue where outage risk is non-trivial.
- Keep kiosk bootstrap QR flow independent of relay choice.

## Common failure patterns

- Relay healthy, cloud unreachable:
  - Expected behavior: local queueing and later replay.
- Relay rejects to cloud with auth/signature/protocol errors:
  - Check shared token, signing secret, protocol version alignment.
- Kiosk cannot reach relay:
  - Check LAN routing/firewall and relay host/port binding.

## Related roadmap context

- Relay capabilities and operations are tracked in stories P1-US-07 through P1-US-10 in [docs/IMPLEMENTATION_STORIES.md](./IMPLEMENTATION_STORIES.md).
- Admin UX for relay and bootstrap credential generation is tracked in P2-US-09.
- Deployment specifics remain in [relay/DEPLOYMENT.md](../relay/DEPLOYMENT.md).

# Wix Scanner Edge Relay Deployment Guide

## Overview

The edge relay is a lightweight FastAPI service that runs on a local venue PC/laptop to accept scans over LAN and forward them to the cloud backend. It provides resilience during WAN outages by acknowledging scans immediately and queuing them for forwarding.

## Deployment Options

### Option 1: Docker (Recommended for Testing)

Use the included relay service in `docker-compose.dev.yml`:

```bash
cd infra/wix_scanner
docker-compose -f docker-compose.dev.yml up relay
```

The relay will be available at `http://localhost:9000`.

### Option 2: Systemd (Production on Linux)

1. Clone the repo to `/opt/wix-scanner-relay` on the venue PC:
```bash
git clone https://github.com/wix-scanner/wix-scanner.git /opt/wix-scanner-relay
cd /opt/wix-scanner-relay/relay
```

2. Create virtual environment and install:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

3. Copy environment configuration:
```bash
cp .env.example .env
# Edit .env to set:
# - WIX_RELAY_CLOUD_BASE_URL (cloud backend URL)
# - WIX_RELAY_RELAY_AUTH_TOKEN (bearer token for cloud auth)
```

4. Make startup script executable:
```bash
chmod +x scripts/wix-scanner-relay-start.sh
```

5. Create systemd user:
```bash
sudo useradd -r -s /bin/false wix
```

6. Copy systemd unit file and enable auto-start:
```bash
sudo cp scripts/wix-scanner-relay.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable wix-scanner-relay
sudo systemctl start wix-scanner-relay
```

7. Check status:
```bash
sudo systemctl status wix-scanner-relay
sudo journalctl -u wix-scanner-relay -f
```

### Option 3: Manual Start

```bash
export WIX_RELAY_CLOUD_BASE_URL=http://backend-ip:8000/api
export WIX_RELAY_RELAY_AUTH_TOKEN=your-relay-auth-token
uvicorn app.main:app --host 0.0.0.0 --port 9000
```

## Configuration

Required environment variables:

- `WIX_RELAY_CLOUD_BASE_URL`: URL of cloud backend (e.g., `http://10.0.0.5:8000/api`)
- `WIX_RELAY_RELAY_AUTH_TOKEN`: Bearer token for cloud authentication

Optional:

- `WIX_RELAY_HOST`: Listen address (default: 0.0.0.0)
- `WIX_RELAY_PORT`: Listen port (default: 9000)
- `WIX_RELAY_CLOUD_REQUEST_TIMEOUT_MS`: Cloud request timeout (default: 5000)

## API Endpoints

### Submit Scan

```bash
curl -X POST http://relay-ip:9000/api/relay/scans \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "evt-123",
    "ticket_number": "TICKET-001",
    "payload": "eventId=evt-123;ticketNumber=TICKET-001",
    "scan_event_id": "550e8400-e29b-41d4-a716-446655440000"
  }'
```

Response:
```json
{
  "acknowledged": true,
  "outcome": "forwarded",
  "message": "Scan forwarded to cloud backend.",
  "relay_request_id": "uuid-here",
  "scan_event_id": "550e8400-e29b-41d4-a716-446655440000",
  "cloud_forwarded": true
}
```

### Health Check

```bash
curl http://relay-ip:9000/api/health
```

Response:
```json
{
  "status": "healthy",
  "relay_ready": true,
  "cloud_reachable": true,
  "cloud_details": {
    "cloud_reachable": true,
    "status_code": 200
  }
}
```

## Troubleshooting

### Relay fails to start
- Check Python version (requires 3.11+)
- Check environment variables are set
- Review logs: `journalctl -u wix-scanner-relay -n 50`

### Scans not forwarding to cloud
- Verify `WIX_RELAY_CLOUD_BASE_URL` is correct and reachable
- Check relay auth token matches backend configuration
- Monitor relay logs and cloud backend logs for errors

### Relay not accepting connections from stations
- Verify firewall rules allow port 9000
- Confirm relay is listening: `netstat -tlnp | grep 9000`
- Test locally first: `curl http://localhost:9000/api/health`

## Monitoring

### Check relay health
```bash
watch -n 5 'curl -s http://relay-ip:9000/api/health | jq'
```

### Stream logs
```bash
sudo journalctl -u wix-scanner-relay -f --lines 100
```

### Count queued scans (with local queue in P1-US-08)
Future: Will be tracked in local SQLite queue.

## Next Steps

- P1-US-08: Implement local durable queue for WAN outage resilience
- P1-US-09: Add end-to-end duplicate prevention via scanEventId
- P1-US-10: Define relay-to-cloud protocol contract

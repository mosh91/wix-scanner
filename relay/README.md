# Wix Scanner Edge Relay

Lightweight local relay service for Wix Scanner that accepts ticket scans over LAN and forwards them to the cloud backend.

## Purpose

Provides resilience during WAN outages by accepting and queuing scans locally before forwarding to the cloud backend.

## Quick Start

```bash
pip install -e .
export WIX_RELAY_CLOUD_BASE_URL=http://backend:8000/api
export WIX_RELAY_RELAY_AUTH_TOKEN=your-relay-auth-token
uvicorn app.main:app --host 0.0.0.0 --port 9000
```

## Environment Configuration

- `WIX_RELAY_CLOUD_BASE_URL`: Cloud backend API base URL (default: http://localhost:8000/api)
- `WIX_RELAY_RELAY_AUTH_TOKEN`: Bearer token for relay authentication to cloud backend
- `WIX_RELAY_HOST`: Relay listen host (default: 0.0.0.0)
- `WIX_RELAY_PORT`: Relay listen port (default: 9000)

## Endpoints

- `POST /api/relay/scans` - Submit a scan from local station
- `GET /api/health` - Health status

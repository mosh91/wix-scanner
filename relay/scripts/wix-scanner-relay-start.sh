#!/bin/bash
# Wix Scanner Edge Relay Auto-Start Script
# Place in /usr/local/bin/wix-scanner-relay-start and make executable
# Then reference in systemd unit file or cron job

set -e

RELAY_DIR="${RELAY_DIR:-.}"
RELAY_VENV="${RELAY_VENV:-.venv}"
RELAY_PORT="${RELAY_PORT:-9000}"
RELAY_LOG="${RELAY_LOG:-/var/log/wix-scanner-relay.log}"

echo "Starting Wix Scanner Edge Relay..."
echo "Directory: $RELAY_DIR"
echo "Port: $RELAY_PORT"
echo "Log: $RELAY_LOG"

cd "$RELAY_DIR"

if [ -f "$RELAY_VENV/bin/activate" ]; then
    source "$RELAY_VENV/bin/activate"
fi

export PYTHONUNBUFFERED=1
uvicorn app.main:app --host 0.0.0.0 --port "$RELAY_PORT" >> "$RELAY_LOG" 2>&1 &

RELAY_PID=$!
echo $RELAY_PID > /var/run/wix-scanner-relay.pid
echo "Relay started with PID $RELAY_PID"

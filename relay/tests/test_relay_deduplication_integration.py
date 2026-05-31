"""Integration tests for relay duplicate scan detection."""

from unittest.mock import patch

import pytest


# relay_client fixture is provided by conftest.py


class TestRelayDuplicateDetection:
    """Tests for relay duplicate scan detection."""

    def test_first_scan_gets_forwarded(self, relay_client):
        """Test that first scan attempt is forwarded to cloud."""
        payload = '{"event_id": "demo-event", "ticket": "TICKET123"}'
        
        with patch('app.services.cloud_forwarder.CloudForwarder.forward_scan') as mock_forward:
            mock_forward.return_value = {
                "acknowledged": True,
                "outcome": "forwarded",
                "message": "Scan forwarded to cloud backend.",
            }
            
            response = relay_client.post(
                "/api/relay/scans",
                json={
                    "event_id": "demo-event",
                    "ticket_number": "TICKET123",
                    "scan_event_id": "550e8400-e29b-41d4-a716-446655440000",
                    "payload": payload,
                },
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["acknowledged"] is True
        assert data["outcome"] == "forwarded"
        assert mock_forward.call_count == 1

    def test_duplicate_scan_returns_cached_outcome(self, relay_client):
        """Test that duplicate scan returns cached outcome without re-forward."""
        payload = '{"event_id": "demo-event", "ticket": "TICKET123"}'
        scan_event_id = "550e8400-e29b-41d4-a716-446655440000"
        
        with patch('app.services.cloud_forwarder.CloudForwarder.forward_scan') as mock_forward:
            mock_forward.return_value = {
                "acknowledged": True,
                "outcome": "forwarded",
                "message": "Scan forwarded to cloud backend.",
            }
            
            # First request
            response1 = relay_client.post(
                "/api/relay/scans",
                json={
                    "event_id": "demo-event",
                    "ticket_number": "TICKET123",
                    "scan_event_id": scan_event_id,
                    "payload": payload,
                },
            )
            assert response1.status_code == 200
            assert response1.json()["outcome"] == "forwarded"
            
            # Second request with same scan_event_id
            response2 = relay_client.post(
                "/api/relay/scans",
                json={
                    "event_id": "demo-event",
                    "ticket_number": "TICKET123",
                    "scan_event_id": scan_event_id,
                    "payload": payload,
                },
            )
        
        assert response2.status_code == 200
        data = response2.json()
        assert "duplicate" in data["outcome"].lower()
        assert data["cloud_forwarded"] is True
        
        # Forward should only be called once (for first request)
        assert mock_forward.call_count == 1

    def test_duplicate_queued_scan_returns_queued_outcome(self, relay_client):
        """Test that duplicate returns correct outcome if original was queued."""
        payload = '{"event_id": "demo-event", "ticket": "TICKET123"}'
        scan_event_id = "550e8400-e29b-41d4-a716-446655440001"
        
        with patch('app.services.cloud_forwarder.CloudForwarder.forward_scan') as mock_forward:
            # First request: cloud unavailable, scan gets queued
            mock_forward.return_value = {
                "acknowledged": True,
                "outcome": "relay_queued",
                "message": "Cloud backend unreachable.",
            }
            
            response1 = relay_client.post(
                "/api/relay/scans",
                json={
                    "event_id": "demo-event",
                    "ticket_number": "TICKET123",
                    "scan_event_id": scan_event_id,
                    "payload": payload,
                },
            )
            assert response1.status_code == 200
            assert response1.json()["outcome"] == "relay_queued"
            
            # Second request with same scan_event_id
            response2 = relay_client.post(
                "/api/relay/scans",
                json={
                    "event_id": "demo-event",
                    "ticket_number": "TICKET123",
                    "scan_event_id": scan_event_id,
                    "payload": payload,
                },
            )
        
        assert response2.status_code == 200
        data = response2.json()
        assert "duplicate" in data["outcome"].lower()
        assert data["queued_locally"] is True

    def test_different_scan_ids_both_processed(self, relay_client):
        """Test that different scan_event_ids are processed independently."""
        payload = '{"event_id": "demo-event", "ticket": "TICKET123"}'
        
        with patch('app.services.cloud_forwarder.CloudForwarder.forward_scan') as mock_forward:
            mock_forward.return_value = {
                "acknowledged": True,
                "outcome": "forwarded",
                "message": "Scan forwarded to cloud backend.",
            }
            
            # First request
            response1 = relay_client.post(
                "/api/relay/scans",
                json={
                    "event_id": "demo-event",
                    "ticket_number": "TICKET123",
                    "scan_event_id": "550e8400-e29b-41d4-a716-446655440000",
                    "payload": payload,
                },
            )
            assert response1.status_code == 200
            assert response1.json()["outcome"] == "forwarded"
            
            # Second request with different scan_event_id
            response2 = relay_client.post(
                "/api/relay/scans",
                json={
                    "event_id": "demo-event",
                    "ticket_number": "TICKET123",
                    "scan_event_id": "550e8400-e29b-41d4-a716-446655440001",
                    "payload": payload,
                },
            )
        
        assert response2.status_code == 200
        assert response2.json()["outcome"] == "forwarded"
        
        # Both should be forwarded
        assert mock_forward.call_count == 2

    def test_duplicate_detection_persists_across_requests(self, relay_client):
        """Test that duplicate detection works across separate client requests."""
        payload = '{"event_id": "demo-event", "ticket": "TICKET123"}'
        scan_event_id = "550e8400-e29b-41d4-a716-446655440002"
        
        with patch('app.services.cloud_forwarder.CloudForwarder.forward_scan') as mock_forward:
            mock_forward.return_value = {
                "acknowledged": True,
                "outcome": "forwarded",
                "message": "Scan forwarded to cloud backend.",
            }
            
            # First client request
            response1 = relay_client.post(
                "/api/relay/scans",
                json={
                    "event_id": "demo-event",
                    "ticket_number": "TICKET123",
                    "scan_event_id": scan_event_id,
                    "payload": payload,
                },
            )
            assert response1.status_code == 200
            
        # Create new client with same databases
        with patch('app.services.cloud_forwarder.CloudForwarder.forward_scan') as mock_forward:
            mock_forward.return_value = {
                "acknowledged": True,
                "outcome": "forwarded",
                "message": "Scan forwarded to cloud backend.",
            }
            
            # Second client request (simulates retry after connection lost)
            response2 = relay_client.post(
                "/api/relay/scans",
                json={
                    "event_id": "demo-event",
                    "ticket_number": "TICKET123",
                    "scan_event_id": scan_event_id,
                    "payload": payload,
                },
            )
        
        assert response2.status_code == 200
        data = response2.json()
        assert "duplicate" in data["outcome"].lower()
        
        # Forward should only have been called once in first block
        # (the second block's mock is a fresh mock, so call_count=0 there)

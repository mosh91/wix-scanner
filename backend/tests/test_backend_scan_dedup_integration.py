"""Integration tests for backend scan deduplication at service level."""

from unittest.mock import patch

import pytest


# backend_client fixture is provided by conftest.py


class TestBackendScanDedup:
    """Test backend duplicate scan detection at service level."""

    def test_scan_idempotency_service_prevents_duplicates(self):
        """Test that scan idempotency service prevents duplicate check-ins."""
        import tempfile
        from pathlib import Path
        from app.services.scan_idempotency import ScanIdempotencyService
        
        # Create service with test database
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db_url = f"sqlite:///{Path(tmpdir) / 'test.db'}"
            service = ScanIdempotencyService(db_url=test_db_url)
            
            event_id = "test-event"
            ticket_number = "T001"
            scan_event_id = "550e8400-e29b-41d4-a716-446655440000"
            
            # First check - should not be duplicate
            result1 = service.check_duplicate(
                event_id=event_id,
                ticket_number=ticket_number,
                scan_event_id=scan_event_id,
            )
            assert result1.is_duplicate is False
            
            # Record the scan
            service.record_scan(
                event_id=event_id,
                ticket_number=ticket_number,
                scan_event_id=scan_event_id,
                outcome="checked_in",
                source="hid",
            )
            
            # Second check - should detect duplicate
            result2 = service.check_duplicate(
                event_id=event_id,
                ticket_number=ticket_number,
                scan_event_id=scan_event_id,
            )
            assert result2.is_duplicate is True
            assert result2.previous_outcome == "checked_in"

    def test_different_scan_ids_not_considered_duplicates(self):
        """Test that different scan_event_ids are not considered duplicates."""
        import tempfile
        from pathlib import Path
        from app.services.scan_idempotency import ScanIdempotencyService
        
        with tempfile.TemporaryDirectory() as tmpdir:
            test_db_url = f"sqlite:///{Path(tmpdir) / 'test.db'}"
            service = ScanIdempotencyService(db_url=test_db_url)
            
            event_id = "test-event"
            ticket_number = "T001"
            
            # Record first scan
            service.record_scan(
                event_id=event_id,
                ticket_number=ticket_number,
                scan_event_id="550e8400-e29b-41d4-a716-446655440001",
                outcome="checked_in",
                source="hid",
            )
            
            # Check with different scan_event_id - should not be duplicate
            result = service.check_duplicate(
                event_id=event_id,
                ticket_number=ticket_number,
                scan_event_id="550e8400-e29b-41d4-a716-446655440002",
            )
            assert result.is_duplicate is False

    def test_duplicate_detection_persists_across_service_instances(self):
        """Test that duplicate detection works across service instances (same DB)."""
        import tempfile
        from pathlib import Path
        from app.services.scan_idempotency import ScanIdempotencyService
        
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            test_db_url = f"sqlite:///{db_path}"
            
            # First service instance: record scan
            service1 = ScanIdempotencyService(db_url=test_db_url)
            service1.record_scan(
                event_id="event-123",
                ticket_number="T001",
                scan_event_id="550e8400-e29b-41d4-a716-446655440003",
                outcome="checked_in",
                source="hid",
            )
            
            # Second service instance: check duplicate (simulates new request)
            service2 = ScanIdempotencyService(db_url=test_db_url)
            result = service2.check_duplicate(
                event_id="event-123",
                ticket_number="T001",
                scan_event_id="550e8400-e29b-41d4-a716-446655440003",
            )
            
            assert result.is_duplicate is True
            assert result.previous_outcome == "checked_in"


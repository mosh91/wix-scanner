"""Tests for backend scan deduplication service."""

import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services.scan_idempotency import (
    ScanIdempotencyRecord,
    ScanIdempotencyService,
    Base,
)


@pytest.fixture
def temp_db():
    """Create temporary SQLite database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_scan_dedup.db"
        db_url = f"sqlite:///{db_path}"
        yield db_url


class TestScanIdempotencyService:
    """Tests for backend scan deduplication service."""

    def test_check_duplicate_returns_false_for_new_scan(self, temp_db):
        """Test check_duplicate returns False for new scan_event_id."""
        service = ScanIdempotencyService(db_url=temp_db)
        
        result = service.check_duplicate(
            event_id="demo-event",
            ticket_number="TICKET123",
            scan_event_id="550e8400-e29b-41d4-a716-446655440000",
        )
        
        assert result.is_duplicate is False
        assert result.previous_outcome is None
        assert result.previous_error is None

    def test_record_scan_creates_record(self, temp_db):
        """Test recording a scan creates a record."""
        service = ScanIdempotencyService(db_url=temp_db)
        
        record = service.record_scan(
            event_id="demo-event",
            ticket_number="TICKET123",
            scan_event_id="550e8400-e29b-41d4-a716-446655440000",
            outcome="CHECKED_IN",
            source="hid",
        )
        
        assert record.event_id == "demo-event"
        assert record.ticket_number == "TICKET123"
        assert record.scan_event_id == "550e8400-e29b-41d4-a716-446655440000"
        assert record.outcome == "CHECKED_IN"
        assert record.source == "hid"

    def test_check_duplicate_returns_true_after_recording(self, temp_db):
        """Test check_duplicate returns True after recording same scan_event_id."""
        service = ScanIdempotencyService(db_url=temp_db)
        scan_event_id = "550e8400-e29b-41d4-a716-446655440000"
        
        # Record first scan
        service.record_scan(
            event_id="demo-event",
            ticket_number="TICKET123",
            scan_event_id=scan_event_id,
            outcome="CHECKED_IN",
            source="hid",
        )
        
        # Check for duplicate
        result = service.check_duplicate(
            event_id="demo-event",
            ticket_number="TICKET123",
            scan_event_id=scan_event_id,
        )
        
        assert result.is_duplicate is True
        assert result.previous_outcome == "CHECKED_IN"

    def test_record_multiple_scans_with_different_ids(self, temp_db):
        """Test recording multiple scans with different scan_event_ids."""
        service = ScanIdempotencyService(db_url=temp_db)
        
        service.record_scan(
            event_id="demo-event",
            ticket_number="TICKET123",
            scan_event_id="550e8400-e29b-41d4-a716-446655440000",
            outcome="CHECKED_IN",
            source="hid",
        )
        
        service.record_scan(
            event_id="demo-event",
            ticket_number="TICKET456",
            scan_event_id="550e8400-e29b-41d4-a716-446655440001",
            outcome="ALREADY_CHECKED_IN",
            source="hid",
        )
        
        # Both should be retrievable
        result1 = service.get_record("550e8400-e29b-41d4-a716-446655440000")
        result2 = service.get_record("550e8400-e29b-41d4-a716-446655440001")
        
        assert result1.outcome == "CHECKED_IN"
        assert result2.outcome == "ALREADY_CHECKED_IN"

    def test_record_scan_with_wix_check_in_id(self, temp_db):
        """Test recording a scan with wix_check_in_id."""
        service = ScanIdempotencyService(db_url=temp_db)
        
        record = service.record_scan(
            event_id="demo-event",
            ticket_number="TICKET123",
            scan_event_id="550e8400-e29b-41d4-a716-446655440000",
            outcome="CHECKED_IN",
            source="hid",
            wix_check_in_id="wix-checkin-id-123",
        )
        
        assert record.wix_check_in_id == "wix-checkin-id-123"

    def test_record_scan_with_error_message(self, temp_db):
        """Test recording a scan with error message."""
        service = ScanIdempotencyService(db_url=temp_db)
        
        record = service.record_scan(
            event_id="demo-event",
            ticket_number="TICKET123",
            scan_event_id="550e8400-e29b-41d4-a716-446655440000",
            outcome="FAILED",
            source="hid",
            error_message="Wix API timeout",
        )
        
        assert record.error_message == "Wix API timeout"
        
        result = service.check_duplicate(
            event_id="demo-event",
            ticket_number="TICKET123",
            scan_event_id="550e8400-e29b-41d4-a716-446655440000",
        )
        
        assert result.previous_error == "Wix API timeout"

    def test_get_record_returns_none_for_missing(self, temp_db):
        """Test get_record returns None for missing record."""
        service = ScanIdempotencyService(db_url=temp_db)
        
        record = service.get_record("nonexistent-id")
        
        assert record is None

    def test_duplicate_scan_event_id_fails_with_unique_constraint(self, temp_db):
        """Test that duplicate scan_event_id fails due to UNIQUE constraint."""
        service = ScanIdempotencyService(db_url=temp_db)
        scan_event_id = "550e8400-e29b-41d4-a716-446655440000"
        
        service.record_scan(
            event_id="demo-event",
            ticket_number="TICKET123",
            scan_event_id=scan_event_id,
            outcome="CHECKED_IN",
            source="hid",
        )
        
        # Attempt to record the same scan_event_id again should raise
        with pytest.raises(Exception):  # SQLAlchemy IntegrityError
            service.record_scan(
                event_id="demo-event",
                ticket_number="TICKET123",
                scan_event_id=scan_event_id,
                outcome="ALREADY_CHECKED_IN",
                source="hid",
            )

    def test_check_duplicate_different_sources(self, temp_db):
        """Test check_duplicate works across different sources."""
        service = ScanIdempotencyService(db_url=temp_db)
        scan_event_id = "550e8400-e29b-41d4-a716-446655440000"
        
        # Record from HID
        service.record_scan(
            event_id="demo-event",
            ticket_number="TICKET123",
            scan_event_id=scan_event_id,
            outcome="CHECKED_IN",
            source="hid",
        )
        
        # Check from relay (different source, same scan_event_id)
        result = service.check_duplicate(
            event_id="demo-event",
            ticket_number="TICKET123",
            scan_event_id=scan_event_id,
        )
        
        assert result.is_duplicate is True
        assert result.previous_outcome == "CHECKED_IN"

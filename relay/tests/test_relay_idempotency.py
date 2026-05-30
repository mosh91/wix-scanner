"""Tests for relay idempotency ledger service."""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from app.services.relay_idempotency import RelayIdempotencyRecord, RelayIdempotencyService


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_relay_idem.db"
        yield str(db_path)


class TestRelayIdempotencyService:
    """Tests for relay idempotency service."""

    def test_record_scan_creates_record(self, temp_db):
        """Test recording a scan creates a record."""
        service = RelayIdempotencyService(db_path=temp_db)
        
        record = service.record_scan(
            scan_event_id="550e8400-e29b-41d4-a716-446655440000",
            relay_id="relay-001",
            outcome="forwarded",
        )
        
        assert record.scan_event_id == "550e8400-e29b-41d4-a716-446655440000"
        assert record.relay_id == "relay-001"
        assert record.outcome == "forwarded"
        assert record.error_message is None
        assert isinstance(record.created_at, datetime)

    def test_find_by_scan_event_id_returns_record(self, temp_db):
        """Test finding a record by scan_event_id."""
        service = RelayIdempotencyService(db_path=temp_db)
        scan_event_id = "550e8400-e29b-41d4-a716-446655440000"
        
        service.record_scan(
            scan_event_id=scan_event_id,
            relay_id="relay-001",
            outcome="forwarded",
        )
        
        found = service.find_by_scan_event_id(scan_event_id)
        
        assert found is not None
        assert found.scan_event_id == scan_event_id
        assert found.relay_id == "relay-001"
        assert found.outcome == "forwarded"

    def test_find_by_scan_event_id_returns_none_for_missing(self, temp_db):
        """Test finding non-existent record returns None."""
        service = RelayIdempotencyService(db_path=temp_db)
        
        found = service.find_by_scan_event_id("nonexistent-id")
        
        assert found is None

    def test_duplicate_scan_event_id_raises_error(self, temp_db):
        """Test that duplicate scan_event_id fails due to UNIQUE constraint."""
        service = RelayIdempotencyService(db_path=temp_db)
        scan_event_id = "550e8400-e29b-41d4-a716-446655440000"
        
        service.record_scan(
            scan_event_id=scan_event_id,
            relay_id="relay-001",
            outcome="forwarded",
        )
        
        # Attempt to record the same scan_event_id again should raise
        with pytest.raises(Exception):  # SQLite IntegrityError
            service.record_scan(
                scan_event_id=scan_event_id,
                relay_id="relay-002",
                outcome="queued",
            )

    def test_record_scan_with_error_message(self, temp_db):
        """Test recording a scan with error message."""
        service = RelayIdempotencyService(db_path=temp_db)
        
        record = service.record_scan(
            scan_event_id="550e8400-e29b-41d4-a716-446655440000",
            relay_id="relay-001",
            outcome="failed",
            error_message="Connection timeout",
        )
        
        assert record.error_message == "Connection timeout"
        
        found = service.find_by_scan_event_id("550e8400-e29b-41d4-a716-446655440000")
        assert found.error_message == "Connection timeout"

    def test_cleanup_old_records(self, temp_db):
        """Test cleanup removes old records."""
        service = RelayIdempotencyService(db_path=temp_db)
        
        # Record a scan
        service.record_scan(
            scan_event_id="550e8400-e29b-41d4-a716-446655440000",
            relay_id="relay-001",
            outcome="forwarded",
        )
        
        # Cleanup records older than 0 days (should delete immediately)
        deleted = service.cleanup_old_records(days_old=0)
        
        assert deleted == 1
        
        # Verify record is gone
        found = service.find_by_scan_event_id("550e8400-e29b-41d4-a716-446655440000")
        assert found is None

    def test_cleanup_preserves_recent_records(self, temp_db):
        """Test cleanup preserves recent records."""
        service = RelayIdempotencyService(db_path=temp_db)
        
        # Record a scan
        service.record_scan(
            scan_event_id="550e8400-e29b-41d4-a716-446655440000",
            relay_id="relay-001",
            outcome="forwarded",
        )
        
        # Cleanup records older than 7 days (should NOT delete recent records)
        deleted = service.cleanup_old_records(days_old=7)
        
        assert deleted == 0
        
        # Verify record still exists
        found = service.find_by_scan_event_id("550e8400-e29b-41d4-a716-446655440000")
        assert found is not None

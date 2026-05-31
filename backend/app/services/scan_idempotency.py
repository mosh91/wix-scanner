"""Backend scan idempotency dedupe ledger for preventing duplicate Wix check-ins."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class ScanIdempotencyRecord(Base):
    """Dedupe ledger entry for a scanned ticket."""

    __tablename__ = "scan_idempotency"

    id = Column(Integer, primary_key=True)
    event_id = Column(String(255), nullable=False, index=True)
    ticket_number = Column(String(255), nullable=False, index=True)
    scan_event_id = Column(String(36), nullable=False, unique=True, index=True)
    wix_check_in_id = Column(String(255), nullable=True)  # From Wix response
    outcome = Column(String(100), nullable=False)  # "CHECKED_IN", "ALREADY_CHECKED_IN", "FAILED", etc.
    error_message = Column(String(512), nullable=True)
    source = Column(String(50), nullable=False)  # "hid", "mobile", "relay", etc.
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("event_id", "ticket_number", "scan_event_id", name="uq_scan_idem"),
    )


@dataclass
class ScanIdempotencyCheckResult:
    """Result of idempotency check."""

    is_duplicate: bool
    previous_outcome: Optional[str]
    previous_error: Optional[str]
    previous_record_id: Optional[int]


class ScanIdempotencyService:
    """Backend dedupe ledger to prevent duplicate Wix check-ins."""

    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def check_duplicate(
        self, event_id: str, ticket_number: str, scan_event_id: str
    ) -> ScanIdempotencyCheckResult:
        """Check if scan_event_id was already processed."""
        with self.SessionLocal() as session:
            record = session.query(ScanIdempotencyRecord).filter_by(
                scan_event_id=scan_event_id
            ).first()

            if not record:
                return ScanIdempotencyCheckResult(
                    is_duplicate=False,
                    previous_outcome=None,
                    previous_error=None,
                    previous_record_id=None,
                )

            return ScanIdempotencyCheckResult(
                is_duplicate=True,
                previous_outcome=record.outcome,
                previous_error=record.error_message,
                previous_record_id=record.id,
            )

    def record_scan(
        self,
        event_id: str,
        ticket_number: str,
        scan_event_id: str,
        outcome: str,
        source: str = "hid",
        wix_check_in_id: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> ScanIdempotencyRecord:
        """Record a scan outcome in dedupe ledger."""
        with self.SessionLocal() as session:
            record = ScanIdempotencyRecord(
                event_id=event_id,
                ticket_number=ticket_number,
                scan_event_id=scan_event_id,
                outcome=outcome,
                source=source,
                wix_check_in_id=wix_check_in_id,
                error_message=error_message,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def get_record(self, scan_event_id: str) -> Optional[ScanIdempotencyRecord]:
        """Retrieve a dedupe record by scan_event_id."""
        with self.SessionLocal() as session:
            return session.query(ScanIdempotencyRecord).filter_by(
                scan_event_id=scan_event_id
            ).first()

    def delete_by_event_id(self, event_id: str) -> int:
        """Delete all scan records for an event. Returns the number of records deleted."""
        with self.SessionLocal() as session:
            count = (
                session.query(ScanIdempotencyRecord)
                .filter_by(event_id=event_id)
                .count()
            )
            session.query(ScanIdempotencyRecord).filter_by(event_id=event_id).delete()
            session.commit()
        return count

    def delete_by_timerange(
        self, event_id: str, starts_at: datetime, ends_at: datetime
    ) -> int:
        """Delete scan records for an event created within [starts_at, ends_at).

        Used for block-level reset: clears scans recorded during the block window.
        Returns the number of records deleted.
        """
        with self.SessionLocal() as session:
            q = session.query(ScanIdempotencyRecord).filter(
                ScanIdempotencyRecord.event_id == event_id,
                ScanIdempotencyRecord.created_at >= starts_at,
                ScanIdempotencyRecord.created_at < ends_at,
            )
            count = q.count()
            q.delete()
            session.commit()
        return count

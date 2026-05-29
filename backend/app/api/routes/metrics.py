from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services.scan_runtime import scan_runtime_store

router = APIRouter(prefix="/metrics")


class ScanMetricQueryRecord(BaseModel):
    timestamp: float
    session_id: str
    operator_id: str
    response_time_ms: int
    latency_percentile: float
    success: bool
    status: str
    error_code: str
    concurrent_count: int
    scanner_status: str
    ticket_number: str
    source: str
    wix_status: str


@router.get("/scans", response_model=list[ScanMetricQueryRecord])
def query_scan_metrics(
    session_id: str | None = Query(default=None),
    operator_id: str | None = Query(default=None),
    start_ts: float | None = Query(default=None, description="Unix timestamp — results at or after this time"),
    end_ts: float | None = Query(default=None, description="Unix timestamp — results at or before this time"),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[ScanMetricQueryRecord]:
    metrics = scan_runtime_store.query_metrics(
        session_id=session_id,
        operator_id=operator_id,
        start_ts=start_ts,
        end_ts=end_ts,
        limit=limit,
    )
    return [ScanMetricQueryRecord.model_validate(item) for item in metrics]

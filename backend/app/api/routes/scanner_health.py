from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.services.scan_runtime import scan_runtime_store
from app.services.ticket_manifest import get_ticket_manifest_service

router = APIRouter(prefix="/health/scanner")


class ScannerHealthResponse(BaseModel):
    backend_status: str
    in_flight: int
    success_rate: float
    last_20_response_times: list[int]
    min_ms: int
    max_ms: int
    avg_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    last_check_ts: int
    manifest_cache_stale: bool = True


class ScanMetricRecord(BaseModel):
    timestamp: float
    session_id: str
    operator_id: str
    response_time_ms: int
    success: bool
    status: str
    error_code: str
    concurrent_count: int
    scanner_status: str
    ticket_number: str
    source: str
    wix_status: str


@router.get("", response_model=ScannerHealthResponse)
def scanner_health(event_id: str | None = Query(default=None)) -> ScannerHealthResponse:
    summary = scan_runtime_store.metrics_summary()
    manifest_stale = True
    if event_id:
        manifest_stale = get_ticket_manifest_service().status(event_id=event_id).stale

    return ScannerHealthResponse(
        backend_status=str(summary["backend_status"] if "backend_status" in summary else summary["status"]),
        in_flight=int(summary["in_flight"]),
        success_rate=float(summary["success_rate"]),
        last_20_response_times=list(summary["last_20_response_times"]),
        min_ms=int(summary["min_ms"]),
        max_ms=int(summary["max_ms"]),
        avg_ms=float(summary["avg_ms"]),
        p50_ms=float(summary["p50_ms"]),
        p95_ms=float(summary["p95_ms"]),
        p99_ms=float(summary["p99_ms"]),
        last_check_ts=int(summary["last_check_ts"]),
        manifest_cache_stale=manifest_stale,
    )


@router.get("/metrics", response_model=list[ScanMetricRecord])
def scanner_metrics() -> list[ScanMetricRecord]:
    return [ScanMetricRecord.model_validate(item) for item in scan_runtime_store.get_metrics()]

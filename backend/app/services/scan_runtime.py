from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
import sqlite3
from statistics import mean
from threading import Lock
from time import perf_counter, time
from pathlib import Path


def _percentile(data: list[int | float], p: float) -> float:
    """Return the p-th percentile of *data* (0–100). Returns 0.0 if data is empty."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = (p / 100) * (len(sorted_data) - 1)
    lower = int(idx)
    upper = min(lower + 1, len(sorted_data) - 1)
    return sorted_data[lower] + (sorted_data[upper] - sorted_data[lower]) * (idx - lower)


@dataclass
class ScanMetric:
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


class ScanRuntimeStore:
    def __init__(self, database_file: Path | None = None) -> None:
        self._metrics: deque[ScanMetric] = deque(maxlen=500)
        self._history: deque[dict[str, str]] = deque(maxlen=25)
        self._in_flight = 0
        self._lock = Lock()
        self._database_file = database_file or Path("./data/scanner_metrics.db")
        self._database_file.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def _initialize_database(self) -> None:
        with sqlite3.connect(self._database_file) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scan_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    session_id TEXT NOT NULL,
                    operator_id TEXT NOT NULL,
                    response_time_ms INTEGER NOT NULL,
                    latency_percentile REAL NOT NULL DEFAULT 0.0,
                    success_status INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    error_code TEXT NOT NULL,
                    concurrent_count INTEGER NOT NULL,
                    scanner_status TEXT NOT NULL,
                    ticket_number TEXT NOT NULL,
                    source TEXT NOT NULL,
                    wix_status TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scan_metrics_hourly (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hour_ts REAL NOT NULL,
                    scan_count INTEGER NOT NULL,
                    success_count INTEGER NOT NULL,
                    avg_response_time_ms REAL NOT NULL,
                    min_response_time_ms INTEGER NOT NULL,
                    max_response_time_ms INTEGER NOT NULL
                )
                """
            )
            # Migrate: add latency_percentile column if it was created without it
            try:
                connection.execute("ALTER TABLE scan_metrics ADD COLUMN latency_percentile REAL NOT NULL DEFAULT 0.0")
            except sqlite3.OperationalError:
                pass  # column already exists
            connection.commit()

    def _insert_metric(self, metric: ScanMetric) -> None:
        with sqlite3.connect(self._database_file) as connection:
            connection.execute(
                """
                INSERT INTO scan_metrics (
                    timestamp,
                    session_id,
                    operator_id,
                    response_time_ms,
                    latency_percentile,
                    success_status,
                    status,
                    error_code,
                    concurrent_count,
                    scanner_status,
                    ticket_number,
                    source,
                    wix_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metric.timestamp,
                    metric.session_id,
                    metric.operator_id,
                    metric.response_time_ms,
                    metric.latency_percentile,
                    1 if metric.success else 0,
                    metric.status,
                    metric.error_code,
                    metric.concurrent_count,
                    metric.scanner_status,
                    metric.ticket_number,
                    metric.source,
                    metric.wix_status,
                ),
            )
            connection.commit()

    def start_request(self) -> float:
        with self._lock:
            self._in_flight += 1
        return perf_counter()

    def finish_request(
        self,
        *,
        started_at: float,
        session_id: str,
        operator_id: str,
        success: bool,
        status: str,
        error_code: str,
        scanner_status: str,
        ticket_number: str,
        source: str,
        wix_status: str,
        reason: str | None,
    ) -> int:
        latency_ms = max(1, int((perf_counter() - started_at) * 1000))
        with self._lock:
            concurrent_count = self._in_flight
            existing_latencies = [m.response_time_ms for m in self._metrics]

        # Compute what percentile this latency falls at among recent requests
        if existing_latencies:
            rank = sum(1 for v in existing_latencies if v <= latency_ms)
            latency_percentile = round((rank / len(existing_latencies)) * 100, 1)
        else:
            latency_percentile = 100.0

        metric = ScanMetric(
            timestamp=time(),
            session_id=session_id,
            operator_id=operator_id,
            response_time_ms=latency_ms,
            latency_percentile=latency_percentile,
            success=success,
            status=status,
            error_code=error_code,
            concurrent_count=concurrent_count,
            scanner_status=scanner_status,
            ticket_number=ticket_number,
            source=source,
            wix_status=wix_status,
        )
        history_item = {
            "timestamp": str(metric.timestamp),
            "session_id": metric.session_id,
            "operator_id": metric.operator_id,
            "ticket_number": ticket_number,
            "status": status,
            "reason": reason or "",
            "response_time_ms": str(latency_ms),
            "wix_status": wix_status,
        }

        with self._lock:
            self._metrics.append(metric)
            self._history.appendleft(history_item)
            self._in_flight = max(0, self._in_flight - 1)

        self._insert_metric(metric)

        return latency_ms

    def metrics_summary(self) -> dict[str, object]:
        with self._lock:
            metrics = list(self._metrics)
            in_flight = self._in_flight

        if not metrics:
            return {
                "status": "yellow",
                "in_flight": in_flight,
                "success_rate": 1.0,
                "last_20_response_times": [],
                "min_ms": 0,
                "max_ms": 0,
                "avg_ms": 0.0,
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "last_check_ts": int(time() * 1000),
            }

        all_latencies = [m.response_time_ms for m in metrics]
        latencies_20 = [m.response_time_ms for m in metrics[-20:]]
        success_rate = len([m for m in metrics if m.success]) / len(metrics)
        health_status = "green" if success_rate >= 0.95 else "yellow" if success_rate >= 0.8 else "red"

        return {
            "status": health_status,
            "in_flight": in_flight,
            "success_rate": round(success_rate, 4),
            "last_20_response_times": latencies_20,
            "min_ms": min(latencies_20),
            "max_ms": max(latencies_20),
            "avg_ms": round(mean(latencies_20), 2),
            "p50_ms": round(_percentile(all_latencies, 50), 2),
            "p95_ms": round(_percentile(all_latencies, 95), 2),
            "p99_ms": round(_percentile(all_latencies, 99), 2),
            "last_check_ts": int(time() * 1000),
        }

    def get_recent_history(self) -> list[dict[str, str]]:
        with self._lock:
            return list(self._history)

    def get_metrics(self) -> list[dict[str, object]]:
        with self._lock:
            return [asdict(item) for item in self._metrics]

    def query_metrics(
        self,
        *,
        session_id: str | None = None,
        operator_id: str | None = None,
        start_ts: float | None = None,
        end_ts: float | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        where_clauses: list[str] = []
        values: list[object] = []

        if session_id:
            where_clauses.append("session_id = ?")
            values.append(session_id)
        if operator_id:
            where_clauses.append("operator_id = ?")
            values.append(operator_id)
        if start_ts is not None:
            where_clauses.append("timestamp >= ?")
            values.append(start_ts)
        if end_ts is not None:
            where_clauses.append("timestamp <= ?")
            values.append(end_ts)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        query = (
            "SELECT timestamp, session_id, operator_id, response_time_ms, latency_percentile, "
            "success_status, status, error_code, concurrent_count, scanner_status, ticket_number, source, wix_status "
            f"FROM scan_metrics {where_sql} ORDER BY id DESC LIMIT ?"
        )
        values.append(max(1, min(limit, 1000)))

        with sqlite3.connect(self._database_file) as connection:
            rows = connection.execute(query, values).fetchall()

        return [
            {
                "timestamp": row[0],
                "session_id": row[1],
                "operator_id": row[2],
                "response_time_ms": row[3],
                "latency_percentile": row[4],
                "success": bool(row[5]),
                "status": row[6],
                "error_code": row[7],
                "concurrent_count": row[8],
                "scanner_status": row[9],
                "ticket_number": row[10],
                "source": row[11],
                "wix_status": row[12],
            }
            for row in rows
        ]

    def cleanup_old_metrics(self) -> dict[str, int]:
        """Archive raw metrics older than 24h into hourly aggregates; purge aggregates older than 30d."""
        now = time()
        cutoff_detail = now - 86400  # 24h
        cutoff_archive = now - 86400 * 30  # 30d

        archived = 0
        purged = 0

        with sqlite3.connect(self._database_file) as connection:
            # Aggregate raw rows older than 24h into hourly buckets
            rows = connection.execute(
                "SELECT timestamp, response_time_ms, success_status FROM scan_metrics WHERE timestamp < ?",
                (cutoff_detail,),
            ).fetchall()

            if rows:
                buckets: dict[int, list[tuple[int, int]]] = defaultdict(list)
                for ts, rms, success in rows:
                    hour = int(ts // 3600) * 3600
                    buckets[hour].append((rms, success))

                for hour_ts, items in buckets.items():
                    scan_count = len(items)
                    success_count = sum(1 for _, s in items if s)
                    avg_ms = sum(r for r, _ in items) / scan_count
                    min_ms = min(r for r, _ in items)
                    max_ms = max(r for r, _ in items)
                    connection.execute(
                        """
                        INSERT INTO scan_metrics_hourly
                            (hour_ts, scan_count, success_count, avg_response_time_ms,
                             min_response_time_ms, max_response_time_ms)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (hour_ts, scan_count, success_count, avg_ms, min_ms, max_ms),
                    )

                cursor = connection.execute(
                    "DELETE FROM scan_metrics WHERE timestamp < ?", (cutoff_detail,)
                )
                archived = cursor.rowcount

            # Purge hourly archive older than 30d
            cursor = connection.execute(
                "DELETE FROM scan_metrics_hourly WHERE hour_ts < ?", (cutoff_archive,)
            )
            purged = cursor.rowcount
            connection.commit()

        return {"archived": archived, "purged": purged}


scan_runtime_store = ScanRuntimeStore()

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import time


@dataclass(frozen=True)
class WorkerHeartbeatRecord:
    worker_name: str
    last_seen_at: float | None
    status: str
    stale_after_s: int


class WorkerHealthService:
    def __init__(self, stale_after_s: int = 10) -> None:
        self._stale_after_s = stale_after_s
        self._lock = Lock()
        self._heartbeats: dict[str, float] = {}

    def pulse(self, worker_name: str) -> None:
        with self._lock:
            self._heartbeats[worker_name] = time()

    def snapshot(self) -> dict[str, WorkerHeartbeatRecord]:
        now = time()
        with self._lock:
            return {
                name: WorkerHeartbeatRecord(
                    worker_name=name,
                    last_seen_at=last_seen,
                    status="healthy" if now - last_seen <= self._stale_after_s else "stale",
                    stale_after_s=self._stale_after_s,
                )
                for name, last_seen in self._heartbeats.items()
            }


_worker_health_service: WorkerHealthService | None = None


def get_worker_health_service() -> WorkerHealthService:
    global _worker_health_service
    if _worker_health_service is None:
        _worker_health_service = WorkerHealthService()
    return _worker_health_service
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from threading import Lock
from time import time

from app.core.config import Settings, get_settings
from app.services.wix_client import WixCheckinResult, get_wix_client

logger = logging.getLogger(__name__)

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover - fallback path for environments without redis package
    redis = None


@dataclass(frozen=True)
class PendingCheckinJob:
    event_id: str
    ticket_number: str
    block_id: str
    operation_type: str
    idempotency_key: str
    correlation_id: str
    attempts: int = 0
    queued_at: float = 0.0


@dataclass(frozen=True)
class EnqueueOutcome:
    enqueued: bool
    reason: str
    queue_depth: int


class _InMemoryOfflineBackend:
    def __init__(self) -> None:
        self._lock = Lock()
        self._processed: dict[str, set[str]] = {}
        self._manifest: dict[str, set[str]] = {}
        self._pending: set[str] = set()
        self._queue: list[str] = []
        self._dlq: list[str] = []

    def _pending_key(self, event_id: str, ticket_number: str) -> str:
        return f"{event_id}:{ticket_number}"

    def enqueue_if_absent(self, *, event_id: str, ticket_number: str, payload: str) -> int:
        with self._lock:
            processed = self._processed.setdefault(event_id, set())
            pending_key = self._pending_key(event_id, ticket_number)
            if ticket_number in processed:
                return -1
            if pending_key in self._pending:
                return 0
            self._pending.add(pending_key)
            self._queue.append(payload)
            return 1

    def queue_depth(self) -> int:
        with self._lock:
            return len(self._queue)

    def mark_processed(self, *, event_id: str, ticket_number: str) -> None:
        with self._lock:
            self._processed.setdefault(event_id, set()).add(ticket_number)

    def is_processed(self, *, event_id: str, ticket_number: str) -> bool:
        with self._lock:
            return ticket_number in self._processed.setdefault(event_id, set())

    def remember_manifest_ticket(self, *, event_id: str, ticket_number: str) -> None:
        with self._lock:
            self._manifest.setdefault(event_id, set()).add(ticket_number)

    def remember_manifest_tickets(self, *, event_id: str, ticket_numbers: list[str]) -> None:
        with self._lock:
            bucket = self._manifest.setdefault(event_id, set())
            for ticket in ticket_numbers:
                bucket.add(ticket)

    def is_manifest_ticket_known(self, *, event_id: str, ticket_number: str) -> bool:
        with self._lock:
            return ticket_number in self._manifest.setdefault(event_id, set())

    def pop_pending(self) -> str | None:
        with self._lock:
            if not self._queue:
                return None
            return self._queue.pop(0)

    def requeue(self, payload: str) -> None:
        with self._lock:
            self._queue.append(payload)

    def clear_pending_marker(self, *, event_id: str, ticket_number: str) -> None:
        with self._lock:
            self._pending.discard(self._pending_key(event_id, ticket_number))

    def move_to_dlq(self, payload: str) -> None:
        with self._lock:
            self._dlq.append(payload)

    def reset(self) -> None:
        with self._lock:
            self._processed.clear()
            self._manifest.clear()
            self._pending.clear()
            self._queue.clear()
            self._dlq.clear()


class OfflineQueueService:
    """Redis-backed offline queue with dedupe guards and worker replay support."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._redis_client = None
        self._memory_backend = _InMemoryOfflineBackend()
        self._enqueue_script = None

        if redis is None:
            logger.warning("offline_queue.redis_unavailable", extra={"mode": "in-memory"})
            return

        try:
            client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            client.ping()
        except Exception as exc:
            logger.warning(
                "offline_queue.redis_connection_failed",
                extra={"mode": "in-memory", "error": type(exc).__name__},
            )
            return

        self._redis_client = client
        self._enqueue_script = client.register_script(
            """
            local processed_set = KEYS[1]
            local pending_marker = KEYS[2]
            local queue_list = KEYS[3]
            local payload = ARGV[1]
            local ttl = tonumber(ARGV[2])
            local ticket = ARGV[3]

            if redis.call('SISMEMBER', processed_set, ticket) == 1 then
                return -1
            end

            if redis.call('EXISTS', pending_marker) == 1 then
                return 0
            end

            redis.call('SET', pending_marker, '1', 'EX', ttl)
            redis.call('RPUSH', queue_list, payload)
            return 1
            """
        )

    def _queue_key(self) -> str:
        return f"{self._settings.redis_key_prefix}:pending:queue"

    def _dlq_key(self) -> str:
        return f"{self._settings.redis_key_prefix}:dead_letter:queue"

    def _processed_key(self, event_id: str) -> str:
        return f"{self._settings.redis_key_prefix}:processed:{event_id}"

    def _manifest_key(self, event_id: str) -> str:
        return f"{self._settings.redis_key_prefix}:manifest:{event_id}"

    def _pending_key(self, event_id: str, ticket_number: str) -> str:
        return f"{self._settings.redis_key_prefix}:pending:{event_id}:{ticket_number}"

    def queue_depth(self) -> int:
        if self._redis_client is None:
            return self._memory_backend.queue_depth()
        return int(self._redis_client.llen(self._queue_key()))

    def is_processed(self, *, event_id: str, ticket_number: str) -> bool:
        if self._redis_client is None:
            return self._memory_backend.is_processed(event_id=event_id, ticket_number=ticket_number)
        return bool(self._redis_client.sismember(self._processed_key(event_id), ticket_number))

    def mark_processed(self, *, event_id: str, ticket_number: str) -> None:
        if self._redis_client is None:
            self._memory_backend.mark_processed(event_id=event_id, ticket_number=ticket_number)
            return
        self._redis_client.sadd(self._processed_key(event_id), ticket_number)

    def remember_manifest_ticket(self, *, event_id: str, ticket_number: str) -> None:
        self.remember_manifest_tickets(event_id=event_id, ticket_numbers=[ticket_number])

    def remember_manifest_tickets(self, *, event_id: str, ticket_numbers: list[str]) -> None:
        if not ticket_numbers:
            return

        if self._redis_client is None:
            self._memory_backend.remember_manifest_tickets(event_id=event_id, ticket_numbers=ticket_numbers)
            return

        key = self._manifest_key(event_id)
        self._redis_client.sadd(key, *ticket_numbers)
        self._redis_client.expire(key, self._settings.manifest_cache_ttl_s)

    def is_manifest_ticket_known(self, *, event_id: str, ticket_number: str) -> bool:
        if self._redis_client is None:
            return self._memory_backend.is_manifest_ticket_known(event_id=event_id, ticket_number=ticket_number)
        return bool(self._redis_client.sismember(self._manifest_key(event_id), ticket_number))

    def enqueue_checkin(self, job: PendingCheckinJob) -> EnqueueOutcome:
        payload = json.dumps(
            {
                "event_id": job.event_id,
                "ticket_number": job.ticket_number,
                "block_id": job.block_id,
                "operation_type": job.operation_type,
                "idempotency_key": job.idempotency_key,
                "correlation_id": job.correlation_id,
                "attempts": job.attempts,
                "queued_at": job.queued_at or time(),
            },
            separators=(",", ":"),
        )

        if self._redis_client is None:
            result = self._memory_backend.enqueue_if_absent(
                event_id=job.event_id,
                ticket_number=job.ticket_number,
                payload=payload,
            )
            depth = self._memory_backend.queue_depth()
            if result == 1:
                return EnqueueOutcome(enqueued=True, reason="enqueued", queue_depth=depth)
            if result == 0:
                return EnqueueOutcome(enqueued=False, reason="duplicate_pending", queue_depth=depth)
            return EnqueueOutcome(enqueued=False, reason="already_processed", queue_depth=depth)

        result = int(
            self._enqueue_script(  # type: ignore[misc]
                keys=[
                    self._processed_key(job.event_id),
                    self._pending_key(job.event_id, job.ticket_number),
                    self._queue_key(),
                ],
                args=[payload, self._settings.pending_marker_ttl_s, job.ticket_number],
            )
        )
        depth = int(self._redis_client.llen(self._queue_key()))
        if result == 1:
            return EnqueueOutcome(enqueued=True, reason="enqueued", queue_depth=depth)
        if result == 0:
            return EnqueueOutcome(enqueued=False, reason="duplicate_pending", queue_depth=depth)
        return EnqueueOutcome(enqueued=False, reason="already_processed", queue_depth=depth)

    def _pop_pending_payload(self) -> str | None:
        if self._redis_client is None:
            return self._memory_backend.pop_pending()
        value = self._redis_client.lpop(self._queue_key())
        return value if isinstance(value, str) else None

    def _requeue_payload(self, payload: str) -> None:
        if self._redis_client is None:
            self._memory_backend.requeue(payload)
            return
        self._redis_client.rpush(self._queue_key(), payload)

    def _clear_pending_marker(self, *, event_id: str, ticket_number: str) -> None:
        if self._redis_client is None:
            self._memory_backend.clear_pending_marker(event_id=event_id, ticket_number=ticket_number)
            return
        self._redis_client.delete(self._pending_key(event_id, ticket_number))

    def _move_to_dlq(self, payload: str) -> None:
        if self._redis_client is None:
            self._memory_backend.move_to_dlq(payload)
            return
        self._redis_client.rpush(self._dlq_key(), payload)

    def process_pending_once(self, *, max_items: int = 20) -> int:
        processed_count = 0

        for _ in range(max(1, max_items)):
            payload = self._pop_pending_payload()
            if payload is None:
                break

            try:
                job = json.loads(payload)
                event_id = str(job["event_id"])
                ticket_number = str(job["ticket_number"])
                attempts = int(job.get("attempts", 0)) + 1
            except Exception:
                logger.warning("offline_queue.invalid_payload", extra={"payload": payload[:200]})
                self._move_to_dlq(payload)
                continue

            wix_result = get_wix_client().check_in_ticket(
                event_id=event_id,
                ticket_number=ticket_number,
                idempotency_key=str(job.get("idempotency_key", "")),
                correlation_id=str(job.get("correlation_id", "offline-worker")),
            )

            if wix_result.outcome in {"checked_in", "already_checked_in"}:
                self.mark_processed(event_id=event_id, ticket_number=ticket_number)
                self.remember_manifest_ticket(event_id=event_id, ticket_number=ticket_number)
                from app.services.ticket_manifest import get_ticket_manifest_service

                get_ticket_manifest_service().mark_checked_in(event_id=event_id, ticket_number=ticket_number)
                self._clear_pending_marker(event_id=event_id, ticket_number=ticket_number)
                processed_count += 1
                continue

            if wix_result.outcome in {"rate_limited", "upstream_error", "transient_error"} and attempts < self._settings.offline_queue_max_attempts:
                job["attempts"] = attempts
                self._requeue_payload(json.dumps(job, separators=(",", ":")))
                continue

            self._move_to_dlq(json.dumps({"job": job, "last_error": wix_result.error_code}, separators=(",", ":")))
            self._clear_pending_marker(event_id=event_id, ticket_number=ticket_number)

        return processed_count

    def reset_for_tests(self) -> None:
        if self._redis_client is None:
            self._memory_backend.reset()
            return

        pattern = f"{self._settings.redis_key_prefix}:*"
        keys = list(self._redis_client.scan_iter(match=pattern, count=500))
        if keys:
            self._redis_client.delete(*keys)


_offline_queue_service: OfflineQueueService | None = None


def get_offline_queue_service() -> OfflineQueueService:
    global _offline_queue_service
    if _offline_queue_service is None:
        _offline_queue_service = OfflineQueueService(get_settings())
    return _offline_queue_service

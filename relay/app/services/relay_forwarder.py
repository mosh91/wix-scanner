from __future__ import annotations

import asyncio
import logging
import random
from typing import Callable

from app.services.cloud_forwarder import CloudForwarder
from app.services.relay_queue import RelayQueueService

logger = logging.getLogger(__name__)


class RelayForwarder:
    """Background service that forwards queued scans to cloud with retry logic."""

    def __init__(
        self,
        queue_service: RelayQueueService,
        cloud_forwarder: CloudForwarder,
        base_backoff_ms: int = 1000,
        max_backoff_ms: int = 30000,
    ) -> None:
        self._queue = queue_service
        self._forwarder = cloud_forwarder
        self._base_backoff_ms = base_backoff_ms
        self._max_backoff_ms = max_backoff_ms
        self._is_running = False

    def _calculate_backoff(self, attempt: int) -> float:
        """Exponential backoff with jitter: base * 2^(attempt-1) + random jitter."""
        if attempt <= 0:
            attempt = 1
        backoff_ms = min(self._base_backoff_ms * (2 ** (attempt - 1)), self._max_backoff_ms)
        jitter_ms = random.randint(0, int(backoff_ms * 0.25))  # 0-25% jitter
        return (backoff_ms + jitter_ms) / 1000.0

    async def process_once(self, batch_size: int = 5) -> dict[str, int]:
        """Process one batch of queued scans. Returns stats."""
        stats = {
            "forwarded": 0,
            "retried": 0,
            "moved_to_dlq": 0,
            "errors": 0,
        }

        pending = self._queue.get_pending_scans(limit=batch_size)
        if not pending:
            return stats

        logger.info(
            "relay.forwarder.batch_start",
            extra={"batch_size": len(pending)},
        )

        for scan in pending:
            try:
                result = self._forwarder.forward_scan(
                    event_id=scan.event_id,
                    ticket_number=scan.ticket_number,
                    relay_request_id=scan.relay_id,
                    payload=scan.payload,
                    correlation_id=scan.correlation_id,
                    scan_event_id=scan.scan_event_id,
                )

                if result.get("outcome") == "forwarded":
                    logger.info(
                        "relay.forwarder.success",
                        extra={
                            "queue_id": scan.id,
                            "event_id": scan.event_id,
                            "attempt": scan.attempt_count + 1,
                        },
                    )
                    self._queue.mark_scan_forwarded(scan.id)
                    stats["forwarded"] += 1
                elif result.get("retryable", True) is False:
                    self._queue.move_to_dlq(
                        scan.id,
                        "contract_rejected",
                        str(result.get("message", "relay_contract_rejected")),
                    )
                    stats["moved_to_dlq"] += 1
                else:
                    # Transient error or cloud unavailable
                    self._queue.increment_attempt(scan.id, str(result.get("message", "transient_error")))
                    stats["retried"] += 1

                    if scan.attempt_count + 1 >= self._queue._max_attempts:
                        self._queue.move_to_dlq(
                            scan.id,
                            "max_retries_exceeded",
                            str(result.get("message", "unknown_error")),
                        )
                        stats["moved_to_dlq"] += 1
                        stats["retried"] -= 1

                        logger.warning(
                            "relay.forwarder.dlq",
                            extra={
                                "queue_id": scan.id,
                                "event_id": scan.event_id,
                                "final_error": result.get("message"),
                            },
                        )

                    # Sleep before next attempt
                    backoff = self._calculate_backoff(scan.attempt_count + 1)
                    await asyncio.sleep(backoff)

            except Exception as exc:
                logger.exception(
                    "relay.forwarder.exception",
                    extra={
                        "queue_id": scan.id,
                        "event_id": scan.event_id,
                    },
                )
                self._queue.increment_attempt(scan.id, str(exc))
                stats["errors"] += 1

        logger.info(
            "relay.forwarder.batch_complete",
            extra=stats,
        )
        return stats

    async def run_loop(self, poll_interval_s: int = 10) -> None:
        """Run forwarder loop continuously."""
        self._is_running = True
        logger.info("relay.forwarder.started", extra={"poll_interval_s": poll_interval_s})

        try:
            while self._is_running:
                try:
                    await self.process_once()
                except Exception as exc:
                    logger.exception("relay.forwarder.loop_error")

                await asyncio.sleep(poll_interval_s)
        finally:
            self._is_running = False
            logger.info("relay.forwarder.stopped")

    def stop(self) -> None:
        """Stop forwarder loop."""
        self._is_running = False

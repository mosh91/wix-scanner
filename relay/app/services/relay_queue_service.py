from __future__ import annotations

from app.services.relay_queue import RelayQueueService

# Global queue instance (initialized on app startup)
_relay_queue: RelayQueueService | None = None


def get_relay_queue() -> RelayQueueService | None:
    """Get the global relay queue instance."""
    return _relay_queue


def set_relay_queue(queue: RelayQueueService) -> None:
    """Set the global relay queue instance (called during app startup)."""
    global _relay_queue
    _relay_queue = queue

import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from app.main import app
from app.services.relay_idempotency import RelayIdempotencyService
from app.services.relay_queue import RelayQueueService
from app.api.routes.scans import set_relay_idempotency
from app.services.relay_queue_service import set_relay_queue


@pytest.fixture
def temp_db_dir():
    """Create temporary directory for test databases (fresh for each test)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def relay_client(temp_db_dir):
    """Create test client with fresh services for each test."""
    # Initialize services with fresh databases for each test
    queue_db = Path(temp_db_dir) / "relay_queue.db"
    idem_db = Path(temp_db_dir) / "relay_idempotency.db"
    
    queue_service = RelayQueueService(db_path=str(queue_db))
    idem_service = RelayIdempotencyService(db_path=str(idem_db))
    
    set_relay_queue(queue_service)
    set_relay_idempotency(idem_service)
    
    # Create test client with app
    client = TestClient(app)
    yield client



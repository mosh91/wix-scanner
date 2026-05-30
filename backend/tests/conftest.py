import sys
from pathlib import Path
import tempfile

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from app.main import app
from app.services.scan_idempotency import ScanIdempotencyService
from app.api.routes.checkins import set_scan_idempotency_service
from app.core.config import get_settings


@pytest.fixture
def temp_db_dir():
    """Create temporary directory for test databases (fresh for each test)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def backend_client(temp_db_dir):
    """Create test client with fresh scan idempotency service for each test."""
    # Create test database URL
    test_db_url = f"sqlite:///{Path(temp_db_dir) / 'test.db'}"
    
    # Initialize scan idempotency service with test database
    idem_service = ScanIdempotencyService(db_url=test_db_url)
    set_scan_idempotency_service(idem_service)
    
    # Create test client with app
    client = TestClient(app)
    yield client


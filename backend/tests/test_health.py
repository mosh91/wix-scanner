from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Wix Scanner Backend",
        "environment": "development",
        "version": "0.1.0",
    }

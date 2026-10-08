"""Tests for the local mock API fixture."""

from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_issue_token_ignores_credentials() -> None:
    response = client.post(
        "/auth/token",
        json={"client_id": "local-client", "client_secret": "not-real"},
    )

    assert response.status_code == 200
    assert response.json() == {"access_token": "mock-access-token"}


def test_known_customer() -> None:
    response = client.get("/customers", params={"customer_id": "12345"})

    assert response.status_code == 200
    assert response.json() == {
        "customer_id": "12345",
        "status": "ACTIVE",
        "last_login": "2026-10-08T10:00:00Z",
    }


def test_other_customer_is_deterministic() -> None:
    first = client.get("/customers", params={"customer_id": "99999"})
    second = client.get("/customers", params={"customer_id": "99999"})

    assert first.status_code == 200
    assert first.json() == second.json()
    assert first.json()["customer_id"] == "99999"


def test_notification_is_acknowledged_without_external_delivery() -> None:
    response = client.post(
        "/notifications",
        json={"customer_id": "12345", "message": "Test notification"},
    )

    assert response.status_code == 200
    assert response.json() == {"success": True, "received": True}

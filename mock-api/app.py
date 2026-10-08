"""Deterministic local HTTP fixture for migrated EUC integration tests."""

from fastapi import FastAPI, Query
from pydantic import BaseModel

app = FastAPI(title="Local EUC Mock API", version="0.1.0")


class TokenRequest(BaseModel):
    """Development-only token request payload."""

    client_id: str
    client_secret: str


@app.get("/health")
def health() -> dict[str, str]:
    """Return the fixture health status."""
    return {"status": "ok"}


@app.post("/auth/token")
def issue_token(_: TokenRequest) -> dict[str, str]:
    """Return a deterministic token without validating credentials."""
    return {"access_token": "mock-access-token"}


@app.get("/customers")
def get_customer(customer_id: str = Query(min_length=1)) -> dict[str, str]:
    """Return a deterministic customer response for any non-empty ID."""
    if customer_id == "12345":
        return {
            "customer_id": "12345",
            "status": "ACTIVE",
            "last_login": "2026-10-08T10:00:00Z",
        }
    return {
        "customer_id": customer_id,
        "status": "ACTIVE",
        "last_login": "2026-10-08T10:00:00Z",
    }


@app.post("/notifications")
def receive_notification(_: dict) -> dict[str, bool]:
    """Accept a notification without sending it externally."""
    return {"success": True, "received": True}

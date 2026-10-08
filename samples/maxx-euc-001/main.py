"""Sanitized representative MAXX Lambda for migration testing."""

import logging

import requests
from sglambdautils.context import LambdaContext  # noqa: F401
from sglambdautils.lambda_secret.secret import get_lambda_secret

LOGGER = logging.getLogger(__name__)
API_URL = "https://example.internal/api"


def send_notification(message: str) -> None:
    """Send a sanitized example email notification."""
    LOGGER.info("Notification for example@example.com: %s", message)


def run(json_input: dict) -> dict:
    """Process an example input and call an external service."""
    client_id = get_lambda_secret("client_id")
    client_secret = get_lambda_secret("client_secret")
    token_response = requests.post(
        f"{API_URL}/token",
        data={"client_id": client_id, "client_secret": client_secret},
        timeout=30,
    )
    token_response.raise_for_status()
    token = token_response.json().get("access_token")

    response = requests.get(
        f"{API_URL}/limits",
        headers={"Authorization": f"Bearer {token}"},
        params=json_input,
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()
    send_notification("Limit processing completed")
    LOGGER.info("Processed MAXX EUC result")
    return result

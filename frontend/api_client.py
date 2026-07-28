"""HTTP client for the FastAPI chat backend."""

from __future__ import annotations

import os
from typing import Any

import requests

DEFAULT_TIMEOUT_SECONDS = 300
HEALTH_TIMEOUT_SECONDS = 5


class ApiClientError(Exception):
    """Raised when the backend returns an error or is unreachable."""


def get_backend_url() -> str:
    """Return the backend base URL from env or localhost default."""
    return os.environ.get("BACKEND_URL", "http://localhost:8080").rstrip("/")


def check_health(base_url: str | None = None) -> bool:
    """Return True if the chat API health endpoint responds with ok status."""
    url = (base_url or get_backend_url()).rstrip("/")
    try:
        response = requests.get(
            f"{url}/api/chats/",
            timeout=HEALTH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("status") == "ok"
    except requests.RequestException:
        return False


def send_message(base_url: str, message: str) -> str:
    """Send a chat message and return the assistant content.

    Args:
        base_url: Backend base URL.
        message: User message text.

    Returns:
        Assistant response content string.

    Raises:
        ApiClientError: On network, timeout, or HTTP errors.
    """
    url = base_url.rstrip("/")
    try:
        response = requests.post(
            f"{url}/api/chats/",
            json={"message": message},
            headers={"Content-Type": "application/json"},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        raise ApiClientError(
            "Request timed out. Research and email flows can take several minutes."
        ) from exc
    except requests.ConnectionError as exc:
        raise ApiClientError(
            "Could not connect to the backend. Check that the API is running."
        ) from exc
    except requests.RequestException as exc:
        raise ApiClientError(f"Request failed: {exc}") from exc

    if not response.ok:
        detail = response.text
        try:
            payload = response.json()
            detail = payload.get("detail", detail)
        except ValueError:
            pass
        raise ApiClientError(f"API error ({response.status_code}): {detail}")

    try:
        data = response.json()
    except ValueError as exc:
        raise ApiClientError("Invalid JSON response from backend.") from exc

    content = data.get("content")
    if content is None:
        raise ApiClientError("Backend response missing 'content' field.")
    return str(content)


def get_recent_messages(base_url: str) -> list[dict[str, Any]]:
    """Fetch the last stored user messages from the backend.

    Args:
        base_url: Backend base URL.

    Returns:
        List of message dicts with id, message, and created_at.

    Raises:
        ApiClientError: On network or HTTP errors.
    """
    url = base_url.rstrip("/")
    try:
        response = requests.get(
            f"{url}/api/chats/recent/",
            timeout=HEALTH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise ApiClientError(f"Failed to fetch recent messages: {exc}") from exc

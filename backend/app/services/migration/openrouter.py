"""Synchronous OpenRouter implementation for the migration transformer."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.services.migration.transformer import TransformationError

DEFAULT_MODEL = "openrouter/free"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
logger = logging.getLogger(__name__)


class OpenRouterProvider:
    """Call OpenRouter's chat completions endpoint synchronously.

    The provider deliberately depends only on the standard library so the
    transformer remains easy to test and the application does not acquire an
    agent framework or vendor SDK dependency.
    """

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60.0,
        opener: Callable[..., object] = urlopen,
    ) -> None:
        if not api_key.strip():
            raise ValueError("OpenRouter API key must not be empty.")
        self._api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._opener = opener

    @classmethod
    def from_environment(cls) -> OpenRouterProvider | None:
        """Create a provider only when an API key is configured."""
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            return None
        return cls(
            api_key=api_key,
            model=os.getenv("LLM_MODEL", "").strip() or DEFAULT_MODEL,
            base_url=os.getenv("OPENROUTER_BASE_URL", "").strip() or DEFAULT_BASE_URL,
        )

    def generate(self, prompt: str) -> str:
        """Generate a transformation response without exposing request data."""
        logger.info("Sending migration transformation request to OpenRouter.")
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            }
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={
                "Authorization": "Bearer " + self._api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with self._opener(request, timeout=self.timeout) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError):
            logger.warning("OpenRouter request failed before a usable response was received.")
            raise TransformationError(
                "OpenRouter request failed while generating the transformation."
            ) from None

        try:
            content = response_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            logger.warning("OpenRouter returned a response without assistant content.")
            raise TransformationError(
                "OpenRouter returned an invalid generation response."
            ) from None
        if not isinstance(content, str) or not content.strip():
            logger.warning("OpenRouter returned empty assistant content.")
            raise TransformationError("OpenRouter returned an empty generation.")
        logger.info("OpenRouter returned assistant content for transformation.")
        return content

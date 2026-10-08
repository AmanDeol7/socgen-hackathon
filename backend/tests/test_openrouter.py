"""Deterministic tests for the OpenRouter provider."""

import json
from typing import Any, Self

import pytest

from app.schemas.migration import EucMetadata
from app.services.migration.analyzer import analyze
from app.services.migration.openrouter import OpenRouterProvider
from app.services.migration.transformer import TransformationError, transform


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def test_generate_posts_expected_request_without_network() -> None:
    captured: dict[str, Any] = {}

    def opener(request: Any, timeout: float) -> FakeResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(
            {"choices": [{"message": {"content": '{"name":"demo"}'}}]}
        )

    provider = OpenRouterProvider(
        "test-key",
        model="openrouter/free",
        base_url="https://router.test/v1",
        timeout=12,
        opener=opener,
    )
    assert provider.generate("transform this") == '{"name":"demo"}'

    request = captured["request"]
    assert request.full_url == "https://router.test/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer " + "test-key"
    assert json.loads(request.data) == {
        "model": "openrouter/free",
        "messages": [{"role": "user", "content": "transform this"}],
        "response_format": {"type": "json_object"},
    }
    assert captured["timeout"] == 12


def test_generate_sanitizes_upstream_failure() -> None:
    def opener(request: Any, timeout: float) -> FakeResponse:
        del request, timeout
        raise OSError("secret upstream response")

    provider = OpenRouterProvider("test-key", opener=opener)
    with pytest.raises(TransformationError, match="OpenRouter request failed"):
        provider.generate("source containing sensitive code")


def test_generate_rejects_malformed_response() -> None:
    provider = OpenRouterProvider(
        "test-key",
        opener=lambda request, timeout: FakeResponse({"choices": []}),
    )
    with pytest.raises(TransformationError, match="invalid generation response"):
        provider.generate("prompt")


def test_from_environment_uses_safe_defaults(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)

    provider = OpenRouterProvider.from_environment()

    assert provider is not None
    assert provider.model == "openrouter/free"
    assert provider.base_url == "https://openrouter.ai/api/v1"


def test_openrouter_provider_integrates_with_transformer() -> None:
    response = {
        "name": "demo",
        "files": [{"path": "src/main.py", "content": "print('ok')\n"}],
        "warnings": [],
        "unsupported_features": [],
    }
    provider = OpenRouterProvider(
        "test-key",
        opener=lambda request, timeout: FakeResponse(
            {"choices": [{"message": {"content": json.dumps(response)}}]}
        ),
    )
    metadata = EucMetadata(
        name="demo",
        owner_team="Example",
        support_team="Example",
    )
    generated = transform(
        "print('source')\n",
        analyze("print('source')\n"),
        metadata,
        "standard specification",
        provider,
    )
    assert generated.name == "demo"
    assert generated.files[0].path == "src/main.py"

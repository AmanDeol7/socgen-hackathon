"""Integration tests for the migration API endpoint."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.migration import get_orchestrator
from app.main import app
from app.services.migration import docker_builder, openrouter
from app.services.migration.orchestrator import MigrationOrchestrator


class ApiProvider:
    """Return a minimal valid EUC for endpoint integration tests."""

    def generate(self, prompt: str) -> str:
        del prompt
        return json.dumps(
            {
                "name": "api-demo",
                "files": [
                    {"path": "src/main.py", "content": "print('ok')\n"},
                    {
                        "path": "src/runner.py",
                        "content": "from src.main import run\n",
                    },
                    {
                        "path": "tests/test_main.py",
                        "content": "def test_ok():\n    assert True\n",
                    },
                    {
                        "path": "config/config.yaml",
                        "content": "endpoint: ${ENDPOINT}\n",
                    },
                    {"path": "requirements.txt", "content": "requests\n"},
                    {"path": "README.md", "content": "# api-demo\n"},
                    {"path": "Dockerfile", "content": "FROM python:3.12-slim\n"},
                ],
                "warnings": [],
                "unsupported_features": [],
            }
        )


class FailingApiProvider:
    """Raise a controlled provider failure."""

    def generate(self, prompt: str) -> str:
        del prompt
        raise RuntimeError("provider unavailable")


def test_post_migrations_returns_completed_result(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        docker_builder.DockerImageBuilder,
        "build",
        lambda self, directory, image, version: None,
    )
    metadata = {
        "name": "api-demo",
        "owner_team": "Example Team",
        "support_team": "Example Support",
    }
    app.dependency_overrides[get_orchestrator] = lambda: MigrationOrchestrator(
        ApiProvider(), tmp_path
    )
    try:
        response = TestClient(app).post(
            "/api/migrations",
            json={
                "metadata": metadata,
                "source_code": "def run(value):\n    return value\n",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"
    assert (tmp_path / "api-demo" / "src" / "main.py").is_file()


def test_post_migrations_returns_failure_information(tmp_path: Path) -> None:
    app.dependency_overrides[get_orchestrator] = lambda: MigrationOrchestrator(
        provider=FailingApiProvider(),
        output_root=tmp_path,
    )
    try:
        response = TestClient(app).post(
            "/api/migrations",
            json={
                "metadata": {
                    "name": "api-demo",
                    "owner_team": "Example Team",
                    "support_team": "Example Support",
                },
                "source_code": "def run(value):\n    return value\n",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "FAILED"
    assert "Transformation failed" in body["validation"]["errors"][0]


def test_dependency_uses_configured_openrouter_provider(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        openrouter.OpenRouterProvider,
        "from_environment",
        lambda: ApiProvider(),
    )
    monkeypatch.setenv("EUC_OUTPUT_ROOT", str(tmp_path))

    orchestrator = get_orchestrator()
    assert isinstance(orchestrator.provider, ApiProvider)

"""Tests for read-only registered EUC artifact endpoints."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.api import eucs
from app.main import app
from app.schemas.execution import EucExecutionMetadata
from app.services.execution.registry import EucRegistry


def _registered_registry(root: Path) -> EucRegistry:
    artifact = root / "customer-greetingggg"
    (artifact / "src").mkdir(parents=True)
    (artifact / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    (artifact / "src" / "main.py").write_text(
        "def run(input_data, context):\n    return input_data\n",
        encoding="utf-8",
    )
    registry = EucRegistry(root)
    registry.register(
        EucExecutionMetadata(
            name="customer-greetingggg",
            image="customer-greetingggg",
            version="latest",
            path=str(artifact),
        )
    )
    return registry


def test_list_eucs_returns_registered_execution_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    registry = _registered_registry(tmp_path)
    monkeypatch.setattr(eucs, "_registry", lambda: registry)

    response = TestClient(app).get("/api/eucs")

    assert response.status_code == 200
    assert response.json() == [
        {
            "name": "customer-greetingggg",
            "image": "customer-greetingggg",
            "version": "latest",
            "status": "REGISTERED",
            "github_repo": None,
            "github_url": None,
            "github_commit_sha": None,
        }
    ]


def test_get_euc_returns_generated_files(
    tmp_path: Path, monkeypatch
) -> None:
    registry = _registered_registry(tmp_path)
    monkeypatch.setattr(eucs, "_registry", lambda: registry)

    response = TestClient(app).get("/api/eucs/customer-greetingggg")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "customer-greetingggg"
    assert payload["version"] == "latest"
    assert payload["status"] == "REGISTERED"
    assert {item["path"] for item in payload["files"]} == {
        "Dockerfile",
        "src/main.py",
    }
    main_source = next(
        item["content"] for item in payload["files"] if item["path"] == "src/main.py"
    )
    assert "def run(input_data, context)" in main_source


def test_get_unknown_euc_returns_404(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(eucs, "_registry", lambda: EucRegistry(tmp_path))

    response = TestClient(app).get("/api/eucs/unknown-euc")

    assert response.status_code == 404


def test_list_includes_existing_artifacts_after_registry_restart(
    tmp_path: Path, monkeypatch
) -> None:
    _registered_registry(tmp_path)
    monkeypatch.setattr(eucs, "_registry", lambda: EucRegistry(tmp_path))

    response = TestClient(app).get("/api/eucs")

    assert response.status_code == 200
    assert response.json() == [
        {
            "name": "customer-greetingggg",
            "image": "customer-greetingggg",
            "version": "latest",
            "status": "ARTIFACT_PRESENT",
            "github_repo": None,
            "github_url": None,
            "github_commit_sha": None,
        }
    ]

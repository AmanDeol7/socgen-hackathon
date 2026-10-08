"""Tests for atomic EUC business-file edits."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.migration import get_orchestrator
from app.main import app
from app.schemas.execution import EucExecutionMetadata
from app.schemas.migration import GeneratedEUC, GeneratedFile
from app.services.execution.registry import EucRegistry
from app.services.migration import docker_builder, generator
from app.services.migration.orchestrator import MigrationOrchestrator

_ORIGINAL_MAIN = "def run(input_data, context):\n    return {'old': True}\n"
_UPDATED_MAIN = "def run(input_data, context):\n    return {'updated': True}\n"
_FILES = [
    GeneratedFile(path="src/main.py", content=_ORIGINAL_MAIN),
    GeneratedFile(path="src/logic.py", content="def value():\n    return 1\n"),
    GeneratedFile(
        path="tests/test_euc_contract.py",
        content="from src.main import run\n\n\ndef test_run():\n    assert callable(run)\n",
    ),
    GeneratedFile(path="src/runner.py", content="def main():\n    return 0\n"),
    GeneratedFile(path="config/config.yaml", content="secret_references:\n  {}\n"),
    GeneratedFile(path="requirements.txt", content="# none\n"),
    GeneratedFile(path="README.md", content="# edit-demo\n"),
    GeneratedFile(path="Dockerfile", content="FROM python:3.12-slim\n"),
]


class FakeBuilder:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.builds: list[tuple[Path, str, str]] = []

    def build(self, path: str | Path, image: str, version: str) -> None:
        build_path = Path(path)
        self.builds.append((build_path, image, version))
        assert (build_path / "src/main.py").is_file()
        if self.fail:
            raise docker_builder.DockerBuildError("test build failure")


@pytest.fixture
def edit_environment(tmp_path: Path):
    artifact = tmp_path / "edit-demo"
    generator.generate_euc(
        GeneratedEUC(
            name="edit-demo",
            files=_FILES,
            warnings=["Initial test artifact."],
            unsupported_features=[],
        ),
        artifact,
    )
    registry = EucRegistry(tmp_path)
    registry.register(
        EucExecutionMetadata(
            name="edit-demo",
            image="edit-demo",
            path=str(artifact),
            owners=["owner@example.com"],
        )
    )
    builder = FakeBuilder()
    orchestrator = MigrationOrchestrator(
        provider=object(),  # edit does not invoke an LLM provider
        output_root=tmp_path,
        registry=registry,
        image_builder=builder,
    )
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    try:
        yield artifact, registry, builder, orchestrator
    finally:
        app.dependency_overrides.pop(get_orchestrator, None)


def _edit(content: str, path: str = "src/main.py"):
    return TestClient(app).put(
        "/api/eucs/edit-demo",
        json={"files": [{"path": path, "content": content}]},
    )


def test_edit_put_preflight_is_allowed() -> None:
    response = TestClient(app).options(
        "/api/eucs/edit-demo",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "PUT" in response.headers["access-control-allow-methods"]


def test_successful_edit_updates_artifact_and_registry(edit_environment) -> None:
    artifact, registry, builder, _ = edit_environment

    response = _edit(_UPDATED_MAIN)

    assert response.status_code == 200
    assert response.json() == {
        "euc_name": "edit-demo",
        "certification_status": "DRAFT",
    }
    assert (artifact / "src/main.py").read_text(encoding="utf-8") == _UPDATED_MAIN
    assert registry.get("edit-demo").path == str(artifact.resolve())
    assert builder.builds[0][1:] == ("edit-demo", "latest")


def test_invalid_python_is_rejected_without_replacing_artifact(edit_environment) -> None:
    artifact, _, builder, _ = edit_environment

    response = _edit("def run(:\n    pass\n")

    assert response.status_code == 422
    assert "unable to parse python source" in response.json()["detail"].lower()
    assert (artifact / "src/main.py").read_text(encoding="utf-8") == _ORIGINAL_MAIN
    assert builder.builds == []


def test_source_without_run_entrypoint_is_rejected(edit_environment) -> None:
    response = _edit("def helper():\n    return True\n")

    assert response.status_code == 422
    assert "run(...) entrypoint" in response.json()["detail"]


def test_maxx_runtime_import_is_rejected(edit_environment) -> None:
    response = _edit(
        "from sglambdautils.context import LambdaContext\n"
        "def run(input_data, context):\n    return input_data\n"
    )

    assert response.status_code == 422
    assert "must not import MAXX runtime modules" in response.json()["detail"]


def test_failed_docker_build_preserves_existing_artifact_and_registry(
    edit_environment,
) -> None:
    artifact, registry, _, orchestrator = edit_environment
    failing_builder = FakeBuilder(fail=True)
    orchestrator.image_builder = failing_builder

    response = _edit(_UPDATED_MAIN)

    assert response.status_code == 502
    assert (artifact / "src/main.py").read_text(encoding="utf-8") == _ORIGINAL_MAIN
    assert registry.get("edit-demo").path == str(artifact.resolve())
    assert registry.get("edit-demo").certification_status == "DRAFT"


def test_editing_certified_euc_invalidates_approval(edit_environment) -> None:
    _, registry, _, _ = edit_environment
    registry.submit_for_certification("edit-demo")
    registry.approve("edit-demo", "owner@example.com")

    response = _edit(_UPDATED_MAIN)

    assert response.status_code == 200
    assert response.json()["certification_status"] == "PENDING_APPROVAL"
    updated = registry.get("edit-demo")
    assert updated.approved_by is None
    assert updated.approved_at is None
    assert updated.rejected_by is None
    assert updated.rejected_at is None
    assert updated.rejection_reason is None


def test_failed_build_does_not_invalidate_certified_euc(edit_environment) -> None:
    artifact, registry, _, orchestrator = edit_environment
    registry.submit_for_certification("edit-demo")
    registry.approve("edit-demo", "owner@example.com")
    failing_builder = FakeBuilder(fail=True)
    orchestrator.image_builder = failing_builder

    response = _edit(_UPDATED_MAIN)

    assert response.status_code == 502
    assert (artifact / "src/main.py").read_text(encoding="utf-8") == _ORIGINAL_MAIN
    assert registry.get("edit-demo").certification_status == "CERTIFIED"
    assert registry.get("edit-demo").approved_by == "owner@example.com"


@pytest.mark.parametrize("status", ["PENDING_APPROVAL", "REJECTED"])
def test_edit_preserves_non_certified_workflow_status(edit_environment, status: str) -> None:
    _, registry, _, _ = edit_environment
    registry.submit_for_certification("edit-demo")
    if status == "REJECTED":
        registry.reject("edit-demo", "owner@example.com", "Needs changes")

    response = _edit(_UPDATED_MAIN)

    assert response.status_code == 200
    assert response.json()["certification_status"] == status
    assert registry.get("edit-demo").certification_fingerprint is not None


def test_platform_owned_and_arbitrary_files_cannot_be_replaced(edit_environment) -> None:
    for path in ("Dockerfile", "src/runner.py", "../escape.py", "tests/test_euc_contract.py"):
        response = _edit("modified\n", path)
        assert response.status_code == 422

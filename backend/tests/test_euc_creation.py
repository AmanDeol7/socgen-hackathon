"""Tests for direct EUC creation and metadata validation."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.migration import get_orchestrator
from app.main import app
from app.schemas.migration import EucMetadata, ValidationResult
from app.services.execution.registry import EucRegistry
from app.services.migration.docker_builder import DockerBuildError, DockerImageBuilder
from app.services.migration.orchestrator import MigrationOrchestrator

_SOURCE = """def run(input_data, context):
    name = input_data.get("name", "world")
    return {"message": f"Hello, {name}!"}
"""


class UnusedProvider:
    def generate(self, prompt: str) -> str:
        raise AssertionError("Direct EUC creation must not call the LLM.")


class SuccessfulBuilder(DockerImageBuilder):
    def __init__(self, registry: EucRegistry | None = None) -> None:
        self.registry = registry

    def build(self, build_directory: Path, image: str, version: str) -> None:
        assert (build_directory / "Dockerfile").is_file()
        assert image == "direct-demo"
        assert version == "latest"
        if self.registry is not None:
            assert not self.registry.exists(image)


def _metadata(**overrides: object) -> dict[str, object]:
    return {
        "name": "direct-demo",
        "owners": ["aman@example.com"],
        **overrides,
    }


def _create_payload(**metadata_overrides: object) -> dict[str, object]:
    return {
        "metadata": _metadata(**metadata_overrides),
        "source_code": _SOURCE,
        "source_filename": "main.py",
    }


def _override_orchestrator(
    tmp_path: Path,
    registry: EucRegistry,
    image_builder: DockerImageBuilder,
) -> MigrationOrchestrator:
    return MigrationOrchestrator(
        provider=UnusedProvider(),
        output_root=tmp_path,
        registry=registry,
        image_builder=image_builder,
    )


def test_metadata_accepts_one_or_multiple_owner_emails() -> None:
    one_owner = EucMetadata.model_validate(_metadata())
    several_owners = EucMetadata.model_validate(
        _metadata(owners=["aman@example.com", "owner2@example.org"])
    )

    assert one_owner.owners == ["aman@example.com"]
    assert several_owners.owners == ["aman@example.com", "owner2@example.org"]


def test_metadata_rejects_empty_owners() -> None:
    with pytest.raises(ValidationError):
        EucMetadata.model_validate(_metadata(owners=[]))


def test_metadata_rejects_invalid_owner_email() -> None:
    with pytest.raises(ValidationError):
        EucMetadata.model_validate(_metadata(owners=["not-an-email"]))


@pytest.mark.parametrize(
    "owner",
    [
        "@example.com",
        "aman..singh@example.com",
        "aman@example",
        "aman@-example.com",
        "aman@example-.com",
        "aman@example.com ",
    ],
)
def test_metadata_rejects_malformed_owner_emails(owner: str) -> None:
    with pytest.raises(ValidationError):
        EucMetadata.model_validate(_metadata(owners=[owner]))


@pytest.mark.parametrize("support_team", ["omitted", None])
def test_metadata_allows_missing_or_null_support_team(support_team: object) -> None:
    values = _metadata()
    if support_team != "omitted":
        values["support_team"] = support_team

    metadata = EucMetadata.model_validate(values)

    assert metadata.support_team is None


def test_direct_creation_validates_builds_and_registers(
    tmp_path: Path,
) -> None:
    registry = EucRegistry(tmp_path)
    orchestrator = _override_orchestrator(
        tmp_path,
        registry,
        SuccessfulBuilder(registry),
    )
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    try:
        response = TestClient(app).post("/api/eucs", json=_create_payload())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"
    assert response.json()["validation"]["valid"] is True
    assert registry.exists("direct-demo")
    registered = registry.get("direct-demo")
    assert registered.certification_status == "DRAFT"
    assert registered.owners == ["aman@example.com"]
    assert (tmp_path / "direct-demo" / "src" / "main.py").read_text() == _SOURCE


def test_direct_creation_rejects_invalid_python_source(
    tmp_path: Path,
) -> None:
    registry = EucRegistry(tmp_path)
    orchestrator = _override_orchestrator(
        tmp_path,
        registry,
        SuccessfulBuilder(registry),
    )
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    try:
        response = TestClient(app).post(
            "/api/eucs",
            json={
                **_create_payload(),
                "source_code": "def run(:\n    return None\n",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "FAILED"
    assert not registry.exists("direct-demo")


def test_direct_creation_rejects_source_without_run_entrypoint(
    tmp_path: Path,
) -> None:
    registry = EucRegistry(tmp_path)
    orchestrator = _override_orchestrator(
        tmp_path,
        registry,
        SuccessfulBuilder(registry),
    )
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    try:
        response = TestClient(app).post(
            "/api/eucs",
            json={**_create_payload(), "source_code": "answer = 42\n"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "FAILED"
    assert "run(...) entrypoint" in response.json()["validation"]["errors"][0]
    assert not registry.exists("direct-demo")


def test_direct_creation_rejects_maxx_runtime_imports(
    tmp_path: Path,
) -> None:
    registry = EucRegistry(tmp_path)
    orchestrator = _override_orchestrator(
        tmp_path,
        registry,
        SuccessfulBuilder(registry),
    )
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    try:
        response = TestClient(app).post(
            "/api/eucs",
            json={
                **_create_payload(),
                "source_code": (
                    "from sglambdautils.context import LambdaContext\n"
                    "def run(input_data, context):\n"
                    "    return input_data\n"
                ),
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "FAILED"
    assert "MAXX runtime modules" in response.json()["validation"]["errors"][0]
    assert not registry.exists("direct-demo")


def test_invalid_generated_artifact_is_not_built_or_registered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.migration.orchestrator as orchestrator_module

    class NeverBuild(DockerImageBuilder):
        def build(self, build_directory: Path, image: str, version: str) -> None:
            raise AssertionError("Invalid generated artifacts must not be built.")

    monkeypatch.setattr(
        orchestrator_module.validator,
        "validate",
        lambda generated: ValidationResult(
            valid=False,
            errors=["Generated artifact is invalid."],
            warnings=[],
        ),
    )
    registry = EucRegistry(tmp_path)
    orchestrator = _override_orchestrator(tmp_path, registry, NeverBuild())
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    try:
        response = TestClient(app).post("/api/eucs", json=_create_payload())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "FAILED"
    assert response.json()["validation"]["errors"] == [
        "Generated artifact is invalid."
    ]
    assert not registry.exists("direct-demo")


def test_docker_build_failure_does_not_register_direct_euc(
    tmp_path: Path,
) -> None:
    class FailingBuilder(DockerImageBuilder):
        def build(self, build_directory: Path, image: str, version: str) -> None:
            raise DockerBuildError("Docker image build failed (exit code 1).")

    registry = EucRegistry(tmp_path)
    orchestrator = _override_orchestrator(tmp_path, registry, FailingBuilder())
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    try:
        response = TestClient(app).post("/api/eucs", json=_create_payload())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "FAILED"
    assert any(
        "Docker build failed" in error
        for error in response.json()["validation"]["errors"]
    )
    assert not registry.exists("direct-demo")
    assert not (tmp_path / "direct-demo").exists()


def test_create_endpoint_rejects_invalid_owner_email(tmp_path: Path) -> None:
    registry = EucRegistry(tmp_path)
    orchestrator = _override_orchestrator(
        tmp_path,
        registry,
        SuccessfulBuilder(registry),
    )
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    try:
        response = TestClient(app).post(
            "/api/eucs",
            json=_create_payload(owners=["invalid-email"]),
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert not registry.exists("direct-demo")

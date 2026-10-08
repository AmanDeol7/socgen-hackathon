"""Tests for EUC certification and the execution approval gate."""

import subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api import eucs
from app.api.execution import get_execution_service
from app.main import app
from app.schemas.execution import EucExecutionMetadata
from app.schemas.migration import GeneratedEUC, GeneratedFile
from app.services.execution.lifecycle import ExecutionLifecycleService, ExecutionStore
from app.services.execution.registry import EucRegistry
from app.services.execution.service import EucCertificationError, ExecutionService
from app.services.migration.generator import generate_euc

_OWNERS = ["owner-a@example.com", "owner-b@example.com"]
_FILES = [
    GeneratedFile(
        path="src/main.py",
        content="def run(input_data, context):\n    return input_data\n",
    ),
    GeneratedFile(path="src/runner.py", content="def main():\n    return 0\n"),
    GeneratedFile(path="config/config.yaml", content="secret_references:\n  {}\n"),
    GeneratedFile(path="requirements.txt", content="# none\n"),
    GeneratedFile(path="README.md", content="# certified-demo\n"),
    GeneratedFile(path="Dockerfile", content="FROM python:3.12-slim\n"),
    GeneratedFile(
        path="tests/test_euc_contract.py",
        content="from src.main import run\n\n\ndef test_run_is_callable():\n    assert callable(run)\n",
    ),
]


def _registered_euc(root: Path, owners: list[str] | None = None) -> EucRegistry:
    artifact = root / "certified-demo"
    generate_euc(
        GeneratedEUC(
            name="certified-demo",
            files=_FILES,
            warnings=["Test EUC"],
            unsupported_features=[],
        ),
        artifact,
    )
    registry = EucRegistry(root)
    registry.register(
        EucExecutionMetadata(
            name="certified-demo",
            image="certified-demo",
            path=str(artifact),
            owners=_OWNERS if owners is None else owners,
            certification_metadata_fingerprint="test-metadata",
        )
    )
    return registry


@pytest.fixture
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> EucRegistry:
    value = _registered_euc(tmp_path)
    monkeypatch.setattr(eucs, "_registry", lambda: value)
    return value


def _submit(name: str = "certified-demo"):
    return TestClient(app).post(f"/api/eucs/{name}/certification/submit")


def _approve(email: str, name: str = "certified-demo"):
    return TestClient(app).post(
        f"/api/eucs/{name}/certification/approve",
        json={"owner_email": email},
    )


def _reject(email: str, reason: str | None = None):
    return TestClient(app).post(
        "/api/eucs/certified-demo/certification/reject",
        json={"owner_email": email, "reason": reason},
    )


def test_new_euc_starts_as_draft(registry: EucRegistry) -> None:
    response = TestClient(app).get("/api/eucs/certified-demo")

    assert response.status_code == 200
    assert response.json()["certification_status"] == "DRAFT"
    assert response.json()["owners"] == _OWNERS


def test_valid_euc_can_be_submitted_for_certification(registry: EucRegistry) -> None:
    response = _submit()

    assert response.status_code == 200
    assert response.json()["certification_status"] == "PENDING_APPROVAL"


@pytest.mark.parametrize("owner", _OWNERS)
def test_any_one_owner_can_approve(registry: EucRegistry, owner: str) -> None:
    _submit()

    response = _approve(owner)

    assert response.status_code == 200
    result = response.json()
    assert result["certification_status"] == "CERTIFIED"
    assert result["approved_by"] == owner
    assert datetime.fromisoformat(result["approved_at"]).tzinfo is not None
    assert result["rejected_by"] is None
    assert result["rejected_at"] is None


def test_non_owner_cannot_approve(registry: EucRegistry) -> None:
    _submit()

    response = _approve("intruder@example.com")

    assert response.status_code == 403
    assert registry.get("certified-demo").certification_status == "PENDING_APPROVAL"


def test_owner_can_reject_and_reason_is_stored(registry: EucRegistry) -> None:
    _submit()

    response = _reject(_OWNERS[1], "Needs review")

    assert response.status_code == 200
    assert response.json()["certification_status"] == "REJECTED"
    assert response.json()["rejected_by"] == _OWNERS[1]
    assert response.json()["rejected_at"]
    assert response.json()["rejection_reason"] == "Needs review"


def test_non_owner_cannot_reject(registry: EucRegistry) -> None:
    _submit()

    response = _reject("intruder@example.com", "Not an owner")

    assert response.status_code == 403
    assert registry.get("certified-demo").certification_status == "PENDING_APPROVAL"


def test_rejected_euc_can_be_resubmitted_and_rejection_is_cleared(
    registry: EucRegistry,
) -> None:
    _submit()
    _reject(_OWNERS[0], "Try again")

    response = _submit()

    assert response.status_code == 200
    assert response.json()["certification_status"] == "PENDING_APPROVAL"
    assert response.json()["rejected_by"] is None
    assert response.json()["rejected_at"] is None
    assert response.json()["rejection_reason"] is None
    assert response.json()["approved_by"] is None
    assert response.json()["approved_at"] is None


def test_submission_rejects_invalid_artifact(
    registry: EucRegistry,
    tmp_path: Path,
) -> None:
    (tmp_path / "certified-demo" / "src" / "main.py").write_text(
        "def run(:\n", encoding="utf-8"
    )

    response = _submit()

    assert response.status_code == 422
    assert registry.get("certified-demo").certification_status == "DRAFT"


def _execution_service(
    root: Path,
    registry: EucRegistry,
) -> ExecutionService:
    return ExecutionService(root, docker_command="docker", registry=registry)


@pytest.mark.parametrize(
    ("state", "transition"),
    [
        ("DRAFT", None),
        ("PENDING_APPROVAL", "submit"),
        ("REJECTED", "reject"),
    ],
)
def test_non_certified_euc_cannot_execute_or_start_docker(
    tmp_path: Path,
    state: str,
    transition: str | None,
) -> None:
    registry = _registered_euc(tmp_path)
    if transition == "submit":
        registry.submit_for_certification("certified-demo")
    elif transition == "reject":
        registry.submit_for_certification("certified-demo")
        registry.reject("certified-demo", _OWNERS[0], "Rejected")
    service = _execution_service(tmp_path, registry)

    with (
        patch("app.services.execution.service.subprocess.run") as docker_run,
        pytest.raises(EucCertificationError),
    ):
        service.execute("certified-demo", {})

    assert registry.get("certified-demo").certification_status == state
    docker_run.assert_not_called()


def test_certified_euc_can_execute(tmp_path: Path) -> None:
    registry = _registered_euc(tmp_path)
    registry.submit_for_certification("certified-demo")
    registry.approve("certified-demo", _OWNERS[0])
    service = _execution_service(tmp_path, registry)
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout='{"ok": true}', stderr=""
    )

    with patch(
        "app.services.execution.service.subprocess.run",
        return_value=completed,
    ) as docker_run:
        result = service.execute("certified-demo", {})

    assert result.status == "COMPLETED"
    docker_run.assert_called_once()


def test_execution_api_rejects_uncertified_euc_without_lifecycle_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _registered_euc(tmp_path)
    execution = ExecutionService(tmp_path, docker_command="docker", registry=registry)
    lifecycle = ExecutionLifecycleService(execution, ExecutionStore())
    monkeypatch.setattr(eucs, "_registry", lambda: registry)
    app.dependency_overrides[get_execution_service] = lambda: lifecycle
    try:
        with patch("app.services.execution.service.subprocess.run") as docker_run:
            response = TestClient(app).post(
                "/api/executions",
                json={"euc_name": "certified-demo", "input": {}},
            )
        assert response.status_code == 409
        assert "not certified" in response.json()["detail"]
        assert lifecycle.list_executions() == []
        docker_run.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_editing_certified_artifact_invalidates_approval(
    registry: EucRegistry,
    tmp_path: Path,
) -> None:
    registry.submit_for_certification("certified-demo")
    registry.approve("certified-demo", _OWNERS[0])
    (tmp_path / "certified-demo" / "src" / "main.py").write_text(
        "def run(input_data, context):\n    return {'changed': True}\n",
        encoding="utf-8",
    )

    response = TestClient(app).get("/api/eucs/certified-demo")

    assert response.status_code == 200
    assert response.json()["certification_status"] == "PENDING_APPROVAL"
    assert response.json()["approved_by"] is None
    assert response.json()["approved_at"] is None


def test_pending_approval_cannot_approve_content_changed_after_submission(
    registry: EucRegistry,
    tmp_path: Path,
) -> None:
    _submit()
    (tmp_path / "certified-demo" / "src" / "main.py").write_text(
        "def run(input_data, context):\n    return {'changed': True}\n",
        encoding="utf-8",
    )

    response = _approve(_OWNERS[0])

    assert response.status_code == 409
    assert registry.get("certified-demo").certification_status == "PENDING_APPROVAL"


def test_changed_certified_euc_returns_to_pending_and_can_be_resubmitted(
    registry: EucRegistry,
    tmp_path: Path,
) -> None:
    _submit()
    _approve(_OWNERS[0])
    (tmp_path / "certified-demo" / "src" / "main.py").write_text(
        "def run(input_data, context):\n    return {'changed': True}\n",
        encoding="utf-8",
    )

    response = _submit()

    assert response.status_code == 200
    assert response.json()["certification_status"] == "PENDING_APPROVAL"
    assert response.json()["approved_by"] is None
    assert response.json()["approved_at"] is None


def test_ownerless_existing_artifact_cannot_be_submitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _registered_euc(tmp_path, owners=[])
    registry = EucRegistry(tmp_path)
    monkeypatch.setattr(eucs, "_registry", lambda: registry)

    response = _submit()

    assert response.status_code == 422
    assert "at least one owner" in response.json()["detail"]
    assert registry.get("certified-demo").certification_status == "DRAFT"

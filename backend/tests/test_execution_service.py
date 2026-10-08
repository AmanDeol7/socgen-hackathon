"""Deterministic tests for the local Docker execution service."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.schemas.execution import EucExecutionMetadata
from app.services.execution.registry import EucRegistry
from app.services.execution.service import ExecutionError, ExecutionService


def _service(
    tmp_path: Path,
    name: str = "demo",
    image: str | None = None,
) -> ExecutionService:
    euc = tmp_path / name
    euc.mkdir()
    (euc / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    registry = EucRegistry(tmp_path)
    registry.register(
        EucExecutionMetadata(
            name=name,
            image=image or name,
            version="latest",
            path=str(euc),
            owners=["owner@example.com"],
        )
    )
    registry.submit_for_certification(name)
    registry.approve(name, "owner@example.com")
    return ExecutionService(
        tmp_path,
        timeout_seconds=2,
        docker_command="docker",
        registry=registry,
    )


def test_execute_success_uses_fixed_docker_arguments(tmp_path: Path) -> None:
    service = _service(tmp_path)
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout='{"processed": 1}\n', stderr=""
    )
    with patch("app.services.execution.service.subprocess.run", return_value=completed) as run:
        result = service.execute("demo", {"records": [1, 2, 3]})

    assert result.status == "COMPLETED"
    assert result.exit_code == 0
    assert result.stdout == '{"processed": 1}'
    run.assert_called_once_with(
        ["docker", "run", "--rm", "-i", "demo"],
        input='{"records": [1, 2, 3]}',
        text=True,
        capture_output=True,
        check=False,
        timeout=2,
        shell=False,
    )


def test_execute_resolves_image_from_registry(tmp_path: Path) -> None:
    service = _service(tmp_path, image="approved-image")
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
    with patch("app.services.execution.service.subprocess.run", return_value=completed) as run:
        service.execute("demo", {})
    assert run.call_args.args[0][-1] == "approved-image"


def test_execute_failed_container_returns_captured_failure(tmp_path: Path) -> None:
    service = _service(tmp_path)
    completed = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="Execution failed"
    )
    with patch("app.services.execution.service.subprocess.run", return_value=completed):
        result = service.execute("demo", {})

    assert result.status == "FAILED"
    assert result.exit_code == 1
    assert result.stderr == "Execution failed"


def test_execute_preserves_malformed_stdout_for_diagnostics(tmp_path: Path) -> None:
    service = _service(tmp_path)
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="not-json\n", stderr=""
    )
    with patch("app.services.execution.service.subprocess.run", return_value=completed):
        result = service.execute("demo", {})

    assert result.status == "COMPLETED"
    assert result.stdout == "not-json"


@pytest.mark.parametrize("name", ["../demo", "..\\demo", "/demo", "demo:latest", ""])
def test_execute_rejects_unsafe_names(tmp_path: Path, name: str) -> None:
    service = _service(tmp_path)
    with pytest.raises(ExecutionError):
        service.execute(name, {})


def test_execute_rejects_missing_euc(tmp_path: Path) -> None:
    service = ExecutionService(tmp_path)
    with pytest.raises(ExecutionError, match="not found"):
        service.execute("missing", {})


def test_execute_handles_timeout(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with patch(
        "app.services.execution.service.subprocess.run",
        side_effect=subprocess.TimeoutExpired(["docker"], 2),
    ):
        result = service.execute("demo", {})

    assert result.status == "TIMED_OUT"
    assert result.exit_code is None
    assert result.stderr == "EUC execution timed out."


def test_execute_handles_docker_start_failure(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with patch(
        "app.services.execution.service.subprocess.run",
        side_effect=OSError("C:\\secret\\docker.exe"),
    ):
        result = service.execute("demo", {})

    assert result.status == "FAILED"
    assert "secret" not in result.stderr.lower()
    assert result.stderr == "Unable to start the Docker execution."


def test_execute_resolves_docker_when_fastapi_path_is_missing(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    service.docker_command = None
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout='{"processed": 1}\n', stderr=""
    )
    with (
        patch(
            "app.services.execution.service.shutil.which",
            return_value=r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
        ),
        patch(
            "app.services.execution.service.subprocess.run",
            return_value=completed,
        ) as run,
    ):
        result = service.execute("demo", {})

    assert result.status == "COMPLETED"
    assert run.call_args.args[0] == [
        r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
        "run",
        "--rm",
        "-i",
        "demo",
    ]


def test_execute_sanitizes_sensitive_output(tmp_path: Path) -> None:
    service = _service(tmp_path)
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=1,
        stdout="token=do-not-return\n",
        stderr="password=do-not-return\n",
    )
    with patch("app.services.execution.service.subprocess.run", return_value=completed):
        result = service.execute("demo", {})

    assert result.stdout == "Execution output suppressed."
    assert result.stderr == "Execution output suppressed."

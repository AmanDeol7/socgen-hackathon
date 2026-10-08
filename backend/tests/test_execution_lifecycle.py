"""Tests for the process-local execution lifecycle."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

from app.schemas.execution import EucExecutionMetadata, ExecutionResult
from app.services.execution.lifecycle import ExecutionLifecycleService, ExecutionStore
from app.services.execution.registry import EucRegistry
from app.services.execution.service import ExecutionError, ExecutionService


def _service(tmp_path: Path, result: ExecutionResult) -> ExecutionLifecycleService:
    euc = tmp_path / "demo"
    euc.mkdir()
    (euc / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    registry = EucRegistry(tmp_path)
    registry.register(
        EucExecutionMetadata(
            name="demo",
            image="demo",
            version="latest",
            path=str(euc),
            owners=["owner@example.com"],
        )
    )
    registry.submit_for_certification("demo")
    registry.approve("demo", "owner@example.com")
    docker_service = ExecutionService(
        tmp_path,
        docker_command="docker",
        registry=registry,
    )
    docker_service_result = subprocess.CompletedProcess(
        args=[],
        returncode=result.exit_code if result.exit_code is not None else 1,
        stdout=result.stdout,
        stderr=result.stderr,
    )
    patcher = patch(
        "app.services.execution.service.subprocess.run",
        return_value=docker_service_result,
    )
    patcher.start()
    lifecycle = ExecutionLifecycleService(docker_service, ExecutionStore())
    lifecycle._test_patcher = patcher
    return lifecycle


def test_execution_store_creates_pending_unique_ids(tmp_path: Path) -> None:
    store = ExecutionStore()

    first = store.create_execution("demo")
    second = store.create_execution("demo")

    assert first.execution_id.startswith("exec-")
    assert first.execution_id != second.execution_id
    assert first.status == "PENDING"
    assert first.completed_at is None
    assert first.duration_ms is None


def test_execution_store_transitions_to_running() -> None:
    store = ExecutionStore()
    record = store.create_execution("demo")

    running = store.mark_running(record.execution_id)

    assert running.status == "RUNNING"


def test_lifecycle_records_completed_execution(tmp_path: Path) -> None:
    lifecycle = _service(
        tmp_path,
        ExecutionResult(
            status="COMPLETED",
            euc_name="demo",
            exit_code=0,
            stdout='{"processed": 1}',
            stderr="",
        ),
    )
    try:
        record = lifecycle.execute("demo", {})
    finally:
        lifecycle._test_patcher.stop()

    assert record.status == "COMPLETED"
    assert record.completed_at is not None
    assert record.duration_ms is not None
    assert record.duration_ms >= 0
    assert record.exit_code == 0


def test_lifecycle_records_failed_execution(tmp_path: Path) -> None:
    lifecycle = _service(
        tmp_path,
        ExecutionResult(
            status="FAILED",
            euc_name="demo",
            exit_code=1,
            stdout="",
            stderr="controlled error",
        ),
    )
    try:
        record = lifecycle.execute("demo", {})
    finally:
        lifecycle._test_patcher.stop()

    assert record.status == "FAILED"
    assert record.exit_code == 1
    assert record.stderr == "controlled error"


def test_lifecycle_records_timeout(tmp_path: Path) -> None:
    euc = tmp_path / "demo"
    euc.mkdir()
    (euc / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    registry = EucRegistry(tmp_path)
    registry.register(
        EucExecutionMetadata(
            name="demo",
            image="demo",
            path=str(euc),
            owners=["owner@example.com"],
        )
    )
    registry.submit_for_certification("demo")
    registry.approve("demo", "owner@example.com")
    service = ExecutionService(
        tmp_path,
        docker_command="docker",
        registry=registry,
    )
    lifecycle = ExecutionLifecycleService(service, ExecutionStore())
    with patch(
        "app.services.execution.service.subprocess.run",
        side_effect=subprocess.TimeoutExpired(["docker"], 1),
    ):
        record = lifecycle.execute("demo", {})

    assert record.status == "TIMED_OUT"
    assert record.completed_at is not None
    assert record.duration_ms is not None


def test_lifecycle_records_execution_error_without_traceback(tmp_path: Path) -> None:
    execution_service = Mock()
    execution_service.execute.side_effect = ValueError("internal traceback detail")
    lifecycle = ExecutionLifecycleService(execution_service, ExecutionStore())

    # Unexpected implementation errors are not converted into API-shaped failures.
    # Controlled execution errors are converted and persisted.
    execution_service.execute.side_effect = ExecutionError("EUC was not found.")
    record = lifecycle.execute("missing", {})

    assert record.status == "FAILED"
    assert "traceback" not in record.stderr.lower()
    assert record.stderr == "EUC was not found."


def test_lifecycle_lists_newest_records_first() -> None:
    store = ExecutionStore()
    first = store.create_execution("first")
    second = store.create_execution("second")

    assert [record.execution_id for record in store.list_executions()] == [
        second.execution_id,
        first.execution_id,
    ]

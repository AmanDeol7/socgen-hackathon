"""API tests for the local execution endpoint."""

from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient

from app.api.execution import get_execution_service
from app.main import app
from app.services.execution.lifecycle import ExecutionLifecycleService, ExecutionStore


def test_post_executions_returns_structured_result(tmp_path: Path) -> None:
    execution_service = Mock()
    execution_service.execute.return_value = Mock(
        status="COMPLETED",
        euc_name="customer-reconciliation",
        exit_code=0,
        stdout='{"processed": 1}\n',
        stderr="",
    )
    service = ExecutionLifecycleService(execution_service, ExecutionStore())
    app.dependency_overrides[get_execution_service] = lambda: service
    try:
        response = TestClient(app).post(
            "/api/executions",
            json={
                "euc_name": "customer-reconciliation",
                "input": {"records": [1, 2, 3]},
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"
    execution_service.execute.assert_called_once_with(
        "customer-reconciliation", {"records": [1, 2, 3]}
    )


def test_get_execution_returns_created_record() -> None:
    execution_service = Mock()
    execution_service.execute.return_value = Mock(
        status="COMPLETED",
        euc_name="demo",
        exit_code=0,
        stdout="ok",
        stderr="",
    )
    service = ExecutionLifecycleService(execution_service, ExecutionStore())
    app.dependency_overrides[get_execution_service] = lambda: service
    try:
        created = TestClient(app).post(
            "/api/executions",
            json={"euc_name": "demo", "input": {}},
        )
        fetched = TestClient(app).get(
            f"/api/executions/{created.json()['execution_id']}"
        )
    finally:
        app.dependency_overrides.clear()

    assert fetched.status_code == 200
    assert fetched.json()["status"] == "COMPLETED"


def test_get_execution_returns_404_for_unknown_id() -> None:
    response = TestClient(app).get("/api/executions/exec-missing")

    assert response.status_code == 404


def test_post_executions_rejects_non_object_input() -> None:
    response = TestClient(app).post(
        "/api/executions",
        json={"euc_name": "demo", "input": ["not", "an", "object"]},
    )

    assert response.status_code == 422

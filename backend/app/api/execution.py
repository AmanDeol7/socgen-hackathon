"""FastAPI endpoint for synchronous local standardized EUC execution."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.schemas.execution import ExecutionInput, ExecutionRecord
from app.services.execution.lifecycle import (
    ExecutionLifecycleService,
    ExecutionNotFoundError,
    ExecutionStore,
)
from app.services.execution.registry import get_registry
from app.services.execution.service import EucCertificationError, ExecutionService

router = APIRouter()


def get_execution_service() -> ExecutionLifecycleService:
    """Build the local Docker execution dependency."""
    service = ExecutionService.from_environment()
    service.registry = get_registry(service.output_root)
    return ExecutionLifecycleService(service, store=_execution_store)


_execution_store = ExecutionStore()


@router.post("/api/executions", response_model=ExecutionRecord)
def create_execution(
    execution_input: ExecutionInput,
    service: Annotated[ExecutionLifecycleService, Depends(get_execution_service)],
) -> ExecutionRecord:
    """Execute an existing standardized EUC synchronously."""
    try:
        return service.execute(execution_input.euc_name, execution_input.input)
    except EucCertificationError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/api/executions/{execution_id}", response_model=ExecutionRecord)
def get_execution(
    execution_id: str,
    service: Annotated[ExecutionLifecycleService, Depends(get_execution_service)],
) -> ExecutionRecord:
    """Return one in-memory execution record."""
    try:
        return service.get_execution(execution_id)
    except ExecutionNotFoundError as error:
        raise HTTPException(status_code=404, detail="Execution not found.") from error


@router.get("/api/executions", response_model=list[ExecutionRecord])
def list_executions(
    service: Annotated[ExecutionLifecycleService, Depends(get_execution_service)],
) -> list[ExecutionRecord]:
    """Return recent in-memory execution records."""
    return service.list_executions()

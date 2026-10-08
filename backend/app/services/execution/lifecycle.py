"""Process-local lifecycle tracking for synchronous EUC executions."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.schemas.execution import ExecutionRecord, ExecutionResult
from app.services.execution.service import ExecutionError, ExecutionService


class ExecutionNotFoundError(KeyError):
    """Raised when a lifecycle record does not exist."""


class ExecutionStore:
    """Keep execution records in memory for the lifetime of the process."""

    def __init__(self) -> None:
        self._records: dict[str, ExecutionRecord] = {}

    def create_execution(self, euc_name: str) -> ExecutionRecord:
        """Create a new execution in the PENDING state."""
        execution_id = f"exec-{uuid4().hex}"
        started_at = _timestamp()
        record = ExecutionRecord(
            execution_id=execution_id,
            euc_name=euc_name,
            status="PENDING",
            started_at=started_at,
            completed_at=None,
            duration_ms=None,
            exit_code=None,
            stdout="",
            stderr="",
        )
        self._records[execution_id] = record
        return record

    def mark_running(self, execution_id: str) -> ExecutionRecord:
        """Move an execution from PENDING to RUNNING."""
        record = self.get_execution(execution_id)
        record.status = "RUNNING"
        return record

    def complete(
        self,
        execution_id: str,
        result: ExecutionResult,
    ) -> ExecutionRecord:
        """Store the terminal Docker result and timing metadata."""
        record = self.get_execution(execution_id)
        completed_at = _timestamp()
        record.status = result.status
        record.completed_at = completed_at
        record.duration_ms = _duration_ms(record.started_at, completed_at)
        record.exit_code = result.exit_code
        record.stdout = result.stdout
        record.stderr = result.stderr
        return record

    def get_execution(self, execution_id: str) -> ExecutionRecord:
        """Return one record or raise a controlled not-found error."""
        try:
            return self._records[execution_id]
        except KeyError as error:
            raise ExecutionNotFoundError(execution_id) from error

    def list_executions(self) -> list[ExecutionRecord]:
        """Return the newest records first."""
        return list(reversed(list(self._records.values())))


class ExecutionLifecycleService:
    """Coordinate lifecycle state around the synchronous execution service."""

    def __init__(
        self,
        execution_service: ExecutionService,
        store: ExecutionStore | None = None,
    ) -> None:
        self.execution_service = execution_service
        self.store = store or ExecutionStore()

    def execute(self, euc_name: str, input_data: dict) -> ExecutionRecord:
        """Create, run, and finalize one execution record."""
        self.execution_service.ensure_certified(euc_name)
        record = self.store.create_execution(euc_name)
        self.store.mark_running(record.execution_id)
        try:
            result = self.execution_service.execute(euc_name, input_data)
        except ExecutionError as error:
            result = ExecutionResult(
                status="FAILED",
                euc_name=euc_name,
                exit_code=None,
                stdout="",
                stderr=str(error),
            )
        return self.store.complete(record.execution_id, result)

    def get_execution(self, execution_id: str) -> ExecutionRecord:
        """Return one stored execution record."""
        return self.store.get_execution(execution_id)

    def list_executions(self) -> list[ExecutionRecord]:
        """Return recent stored execution records."""
        return self.store.list_executions()


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _duration_ms(started_at: str, completed_at: str) -> int:
    started = datetime.fromisoformat(started_at)
    completed = datetime.fromisoformat(completed_at)
    return max(0, round((completed - started).total_seconds() * 1000))

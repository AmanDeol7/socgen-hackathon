"""Pydantic contracts for local standardized EUC execution."""

from typing import Literal

from pydantic import BaseModel, Field


class ExecutionInput(BaseModel):
    """Request to execute an existing standardized EUC."""

    euc_name: str = Field(min_length=1)
    input: dict


class EucExecutionMetadata(BaseModel):
    """Authoritative local artifact metadata for one executable EUC."""

    name: str = Field(min_length=1)
    image: str = Field(min_length=1)
    version: str = Field(default="latest", min_length=1)
    path: str = Field(min_length=1)
    github_repo: str | None = None
    github_url: str | None = None
    github_commit_sha: str | None = None


class ExecutionResult(BaseModel):
    """Result captured from one Docker-backed EUC execution."""

    status: Literal["COMPLETED", "FAILED", "TIMED_OUT"]
    euc_name: str
    exit_code: int | None
    stdout: str
    stderr: str


class ExecutionRecord(BaseModel):
    """In-memory lifecycle record for one execution."""

    execution_id: str
    euc_name: str
    status: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED", "TIMED_OUT"]
    started_at: str
    completed_at: str | None
    duration_ms: int | None
    exit_code: int | None
    stdout: str
    stderr: str

"""Pydantic contracts for local standardized EUC execution."""

from typing import Literal

from pydantic import BaseModel, Field

CertificationStatus = Literal[
    "DRAFT",
    "PENDING_APPROVAL",
    "CERTIFIED",
    "REJECTED",
]


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
    owners: list[str] = Field(default_factory=list)
    certification_status: CertificationStatus = "DRAFT"
    approved_by: str | None = None
    approved_at: str | None = None
    rejected_by: str | None = None
    rejected_at: str | None = None
    rejection_reason: str | None = None
    certification_fingerprint: str | None = None
    certification_metadata_fingerprint: str | None = None
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

"""Create EUCs and read local generated artifacts."""

import os
import re
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.migration import get_orchestrator
from app.schemas.execution import CertificationStatus, EucExecutionMetadata
from app.schemas.migration import GeneratedFile, MigrationInput, MigrationResult
from app.services.execution.registry import (
    CertificationMetadataError,
    CertificationOwnerError,
    CertificationStateError,
    EucNotFoundError,
    EucRegistry,
    RegistryError,
    get_registry,
)
from app.services.github import (
    GitHubConfigurationError,
    GitHubSaveError,
    GitHubService,
)
from app.services.migration import docker_builder, validator
from app.services.migration.orchestrator import MigrationOrchestrator

router = APIRouter()


class EucSummary(BaseModel):
    name: str
    image: str
    version: str
    status: Literal["REGISTERED", "ARTIFACT_PRESENT"]
    owners: list[str] = Field(default_factory=list)
    certification_status: CertificationStatus = "DRAFT"
    approved_by: str | None = None
    approved_at: str | None = None
    rejected_by: str | None = None
    rejected_at: str | None = None
    rejection_reason: str | None = None
    github_repo: str | None = None
    github_url: str | None = None
    github_commit_sha: str | None = None


class EucDetails(EucSummary):
    files: list[GeneratedFile]


class GitHubSaveResponse(BaseModel):
    euc_name: str
    github_repo: str
    github_url: str
    github_commit_sha: str


class CertificationActionRequest(BaseModel):
    owner_email: str = Field(min_length=1)


class CertificationRejectRequest(CertificationActionRequest):
    reason: str | None = None


class CertificationResponse(BaseModel):
    euc_name: str
    owners: list[str]
    certification_status: CertificationStatus
    approved_by: str | None
    approved_at: str | None
    rejected_by: str | None
    rejected_at: str | None
    rejection_reason: str | None


class EucEditRequest(BaseModel):
    files: list[GeneratedFile] = Field(min_length=1)


class EucEditResponse(BaseModel):
    euc_name: str
    certification_status: CertificationStatus


def _registry() -> EucRegistry:
    return get_registry(Path(os.getenv("EUC_OUTPUT_ROOT", "output")))


def _certification_fields(
    entry: EucExecutionMetadata | None,
) -> dict[str, object]:
    if entry is None:
        return {
            "owners": [],
            "certification_status": "DRAFT",
            "approved_by": None,
            "approved_at": None,
            "rejected_by": None,
            "rejected_at": None,
            "rejection_reason": None,
        }
    return {
        "owners": entry.owners,
        "certification_status": entry.certification_status,
        "approved_by": entry.approved_by,
        "approved_at": entry.approved_at,
        "rejected_by": entry.rejected_by,
        "rejected_at": entry.rejected_at,
        "rejection_reason": entry.rejection_reason,
    }


def _certification_entry(
    registry: EucRegistry,
    name: str,
) -> EucExecutionMetadata:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) or name in {
        ".",
        "..",
    }:
        raise HTTPException(status_code=404, detail="EUC not found.")
    try:
        try:
            return registry.get(name)
        except EucNotFoundError:
            registry.register_existing(name)
            return registry.get(name)
    except RegistryError as error:
        raise HTTPException(status_code=404, detail="EUC not found.") from error


def _certification_response(entry: EucExecutionMetadata) -> CertificationResponse:
    return CertificationResponse(
        euc_name=entry.name,
        **_certification_fields(entry),
    )


def _validated_certification_artifact(
    entry: EucExecutionMetadata,
) -> None:
    validation = validator.validate_directory(Path(entry.path))
    if not validation.valid:
        raise HTTPException(
            status_code=422,
            detail="Generated EUC artifact is invalid for certification.",
        )


def _refresh_certification(
    registry: EucRegistry,
    name: str,
) -> EucExecutionMetadata:
    try:
        return registry.refresh_certification(name)
    except RegistryError as error:
        raise HTTPException(
            status_code=422,
            detail="Unable to verify EUC certification against its generated files.",
        ) from error


@router.post(
    "/api/eucs/{name}/certification/submit",
    response_model=CertificationResponse,
)
def submit_euc_for_certification(name: str) -> CertificationResponse:
    """Validate and place an existing generated EUC into the approval queue."""
    registry = _registry()
    entry = _certification_entry(registry, name)
    _validated_certification_artifact(entry)
    try:
        return _certification_response(registry.submit_for_certification(name))
    except CertificationMetadataError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except CertificationStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post(
    "/api/eucs/{name}/certification/approve",
    response_model=CertificationResponse,
)
def approve_euc(
    name: str,
    request: CertificationActionRequest,
) -> CertificationResponse:
    """Approve a pending EUC when the email belongs to one of its owners."""
    registry = _registry()
    entry = _certification_entry(registry, name)
    _validated_certification_artifact(entry)
    try:
        return _certification_response(registry.approve(name, request.owner_email))
    except CertificationOwnerError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except CertificationStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except CertificationMetadataError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/api/eucs/{name}/certification/reject",
    response_model=CertificationResponse,
)
def reject_euc(
    name: str,
    request: CertificationRejectRequest,
) -> CertificationResponse:
    """Reject a pending EUC when the email belongs to one of its owners."""
    registry = _registry()
    entry = _certification_entry(registry, name)
    _validated_certification_artifact(entry)
    try:
        return _certification_response(
            registry.reject(name, request.owner_email, request.reason)
        )
    except CertificationOwnerError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except CertificationStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post(
    "/api/eucs/{name}/github",
    response_model=GitHubSaveResponse,
)
def save_euc_to_github(name: str) -> GitHubSaveResponse:
    """Commit a complete validated EUC artifact to its configured organization."""
    registry = _registry()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) or name in {
        ".",
        "..",
    }:
        raise HTTPException(status_code=404, detail="EUC not found.")
    try:
        registered = registry.get(name)
        registered = _refresh_certification(registry, name)
        artifact_path = Path(registered.path).resolve()
        artifact_path.relative_to(registry.output_root)
    except (EucNotFoundError, RegistryError, ValueError):
        artifact_path = (registry.output_root / name).resolve()
        try:
            artifact_path.relative_to(registry.output_root)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="EUC not found.") from error
    if not artifact_path.is_dir() or not (artifact_path / "Dockerfile").is_file():
        raise HTTPException(status_code=404, detail="EUC not found.")

    validation = validator.validate_directory(artifact_path)
    if not validation.valid:
        raise HTTPException(
            status_code=422,
            detail="Generated EUC artifact is invalid and cannot be saved to GitHub.",
        )
    try:
        result = GitHubService().save(name, artifact_path)
    except GitHubConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except GitHubSaveError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    registry.update_github(
        name,
        result["github_repo"],
        result["github_url"],
        result["github_commit_sha"],
    )
    return GitHubSaveResponse(**result)


@router.post("/api/eucs", response_model=MigrationResult)
def create_euc(
    create_input: MigrationInput,
    orchestrator: Annotated[MigrationOrchestrator, Depends(get_orchestrator)],
) -> MigrationResult:
    """Create and materialize an EUC from platform-compatible Python source."""
    return orchestrator.create_euc(create_input)


@router.put("/api/eucs/{name}", response_model=EucEditResponse)
def edit_euc(
    name: str,
    request: EucEditRequest,
    orchestrator: Annotated[MigrationOrchestrator, Depends(get_orchestrator)],
) -> EucEditResponse:
    """Edit supported business Python files and atomically rebuild an EUC."""
    try:
        updated = orchestrator.edit_euc(name, request.files)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except docker_builder.DockerBuildError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return EucEditResponse(
        euc_name=updated.name,
        certification_status=updated.certification_status,
    )


@router.get("/api/eucs", response_model=list[EucSummary])
def list_eucs() -> list[EucSummary]:
    """List registered EUCs and generated artifacts available on disk."""
    registry = _registry()
    items = {
        item.name: EucSummary(
            name=item.name,
            image=item.image,
            version=item.version,
            status="REGISTERED",
            **_certification_fields(_refresh_certification(registry, item.name)),
            **registry.github_metadata(item.name),
        )
        for item in registry.list()
    }
    if registry.output_root.is_dir():
        for artifact in registry.output_root.iterdir():
            if (
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", artifact.name)
                or not artifact.is_dir()
                or not (artifact / "Dockerfile").is_file()
            ):
                continue
            try:
                artifact.resolve().relative_to(registry.output_root)
            except ValueError:
                continue
            items.setdefault(
                artifact.name,
                EucSummary(
                    name=artifact.name,
                    image=artifact.name,
                    version="latest",
                    status="ARTIFACT_PRESENT",
                    **_certification_fields(None),
                    **registry.github_metadata(artifact.name),
                ),
            )
    return [items[name] for name in sorted(items)]


@router.get("/api/eucs/{name}", response_model=EucDetails)
def get_euc(name: str) -> EucDetails:
    """Return registered execution metadata and generated artifact contents."""
    registry = _registry()
    try:
        metadata = registry.get(name)
        metadata = _refresh_certification(registry, name)
        artifact_path = Path(metadata.path).resolve()
        status: Literal["REGISTERED", "ARTIFACT_PRESENT"] = "REGISTERED"
    except (EucNotFoundError, RegistryError):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
            raise HTTPException(status_code=404, detail="EUC not found.")
        artifact_path = (registry.output_root / name).resolve()
        try:
            artifact_path.relative_to(registry.output_root)
        except ValueError as error:
            raise HTTPException(status_code=404, detail="EUC not found.") from error
        if not artifact_path.is_dir() or not (artifact_path / "Dockerfile").is_file():
            raise HTTPException(status_code=404, detail="EUC not found.")
        metadata = None
        status = "ARTIFACT_PRESENT"

    files: list[GeneratedFile] = []
    for path in sorted(artifact_path.rglob("*")):
        if not path.is_file():
            continue
        try:
            relative_path = path.resolve().relative_to(artifact_path).as_posix()
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError) as error:
            raise HTTPException(
                status_code=500,
                detail="Unable to read a generated EUC artifact safely.",
            ) from error
        files.append(GeneratedFile(path=relative_path, content=content))

    return EucDetails(
        name=name,
        image=metadata.image if metadata else name,
        version=metadata.version if metadata else "latest",
        status=status,
        **_certification_fields(metadata),
        **registry.github_metadata(name),
        files=files,
    )

"""Create EUCs and read local generated artifacts."""

import os
import re
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.migration import get_orchestrator
from app.schemas.migration import GeneratedFile, MigrationInput, MigrationResult
from app.services.execution.registry import (
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
from app.services.migration import validator
from app.services.migration.orchestrator import MigrationOrchestrator

router = APIRouter()


class EucSummary(BaseModel):
    name: str
    image: str
    version: str
    status: Literal["REGISTERED", "ARTIFACT_PRESENT"]
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


def _registry() -> EucRegistry:
    return get_registry(Path(os.getenv("EUC_OUTPUT_ROOT", "output")))


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
        **registry.github_metadata(name),
        files=files,
    )

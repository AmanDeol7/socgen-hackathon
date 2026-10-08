"""Read-only API access to registered EUC artifacts."""

import os
import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.schemas.migration import GeneratedFile
from app.services.execution.registry import (
    EucNotFoundError,
    EucRegistry,
    RegistryError,
    get_registry,
)

router = APIRouter()


class EucSummary(BaseModel):
    name: str
    image: str
    version: str
    status: Literal["REGISTERED", "ARTIFACT_PRESENT"]


class EucDetails(EucSummary):
    files: list[GeneratedFile]


def _registry() -> EucRegistry:
    return get_registry(Path(os.getenv("EUC_OUTPUT_ROOT", "output")))


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
        files=files,
    )

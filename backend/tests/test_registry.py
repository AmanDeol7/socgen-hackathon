"""Tests for the local in-memory EUC registry."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.execution import EucExecutionMetadata
from app.services.execution.registry import (
    DuplicateEucError,
    EucNotFoundError,
    EucRegistry,
    RegistryError,
)


def _metadata(root: Path, name: str = "demo") -> EucExecutionMetadata:
    path = root / name
    path.mkdir()
    (path / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    return EucExecutionMetadata(
        name=name, image=name, version="latest", path=str(path)
    )


def test_register_get_exists_and_list(tmp_path: Path) -> None:
    registry = EucRegistry(tmp_path)
    metadata = _metadata(tmp_path)
    registry.register(metadata)

    assert registry.get("demo") == metadata.model_copy(update={"path": str((tmp_path / "demo").resolve())})
    assert registry.exists("demo")
    assert [entry.name for entry in registry.list()] == ["demo"]


def test_registry_rejects_duplicates_and_unknown_names(tmp_path: Path) -> None:
    registry = EucRegistry(tmp_path)
    metadata = _metadata(tmp_path)
    registry.register(metadata)
    with pytest.raises(DuplicateEucError):
        registry.register(metadata)
    with pytest.raises(EucNotFoundError):
        registry.get("missing")


@pytest.mark.parametrize("name", ["../demo", "..\\demo", "/demo", "demo:latest", ""])
def test_registry_rejects_unsafe_names(tmp_path: Path, name: str) -> None:
    registry = EucRegistry(tmp_path)
    with pytest.raises((RegistryError, ValidationError)):
        registry.register(
            EucExecutionMetadata(
                name=name,
                image="demo",
                version="latest",
                path=str(tmp_path / "demo"),
            )
        )


def test_registry_rejects_invalid_metadata_path_and_image(tmp_path: Path) -> None:
    registry = EucRegistry(tmp_path)
    outside = tmp_path.parent / "outside"
    outside.mkdir()
    with pytest.raises(RegistryError):
        registry.register(
            EucExecutionMetadata(
                name="demo",
                image="other:latest",
                version="latest",
                path=str(outside),
            )
        )

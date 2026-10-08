"""Tests for the migration orchestrator."""

import json
from pathlib import Path

import pytest
from app.schemas.migration import (
    CodeAnalysis,
    EucMetadata,
    GeneratedEUC,
    GeneratedFile,
    MigrationInput,
)
from app.services.migration import orchestrator


class FakeProvider:
    """Return a deterministic standardized EUC."""

    def __init__(self, metadata: EucMetadata) -> None:
        self.metadata = metadata

    def generate(self, prompt: str) -> str:
        del prompt
        return json.dumps(
            {
                "name": self.metadata.name,
                "files": [
                    {"path": "src/main.py", "content": "print('ok')\n"},
                    {
                        "path": "tests/test_main.py",
                        "content": "def test_ok():\n    assert True\n",
                    },
                    {
                        "path": "config/config.yaml",
                        "content": "endpoint: ${ENDPOINT}\n",
                    },
                    {"path": "requirements.txt", "content": "requests\n"},
                    {"path": "README.md", "content": "# demo\n"},
                    {"path": "Dockerfile", "content": "FROM python:3.12-slim\n"},
                ],
                "warnings": ["Example warning."],
                "unsupported_features": ["Example unsupported feature."],
            }
        )


class FailingProvider:
    """Raise a controlled provider failure."""

    def generate(self, prompt: str) -> str:
        del prompt
        raise RuntimeError("provider secret=do-not-expose")


class LeakingTransformationProvider:
    """Raise a transformation error containing sensitive details."""

    def generate(self, prompt: str) -> str:
        del prompt
        raise orchestrator.transformer.TransformationError(
            "provider api_key=do-not-expose"
        )


@pytest.fixture
def metadata() -> EucMetadata:
    return EucMetadata(
        name="demo-euc",
        owner_team="Example Team",
        support_team="Example Support",
    )


@pytest.fixture
def migration_input(metadata: EucMetadata) -> MigrationInput:
    return MigrationInput(
        metadata=metadata,
        source_code="def run(value):\n    return value\n",
    )


def test_successful_migration_writes_named_output_directory(
    migration_input: MigrationInput,
    metadata: EucMetadata,
    tmp_path: Path,
) -> None:
    result = orchestrator.MigrationOrchestrator(
        FakeProvider(metadata), tmp_path
    ).migrate(migration_input)

    assert result.status == "COMPLETED"
    assert result.validation.valid
    assert result.generated_euc.warnings == ["Example warning."]
    assert result.generated_euc.unsupported_features == [
        "Example unsupported feature."
    ]
    assert (tmp_path / metadata.name / "src/main.py").is_file()


def test_invalid_generated_euc_is_not_materialized(
    migration_input: MigrationInput,
    metadata: EucMetadata,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated = GeneratedEUC(
        name=metadata.name,
        files=[],
        warnings=[],
        unsupported_features=[],
    )
    monkeypatch.setattr(
        orchestrator.transformer,
        "transform",
        lambda *args: generated,
    )

    result = orchestrator.MigrationOrchestrator(
        FakeProvider(metadata), tmp_path
    ).migrate(migration_input)

    assert result.status == "FAILED"
    assert not (tmp_path / metadata.name).exists()
    assert result.validation.errors


def test_provider_failure_returns_failed_result(
    migration_input: MigrationInput, tmp_path: Path
) -> None:
    result = orchestrator.MigrationOrchestrator(
        FailingProvider(), tmp_path
    ).migrate(migration_input)

    assert result.status == "FAILED"
    assert any("Transformation failed" in error for error in result.validation.errors)
    assert all("do-not-expose" not in error for error in result.validation.errors)
    assert not list(tmp_path.iterdir())


def test_uncontrolled_transformation_error_is_not_exposed(
    migration_input: MigrationInput, tmp_path: Path
) -> None:
    result = orchestrator.MigrationOrchestrator(
        LeakingTransformationProvider(), tmp_path
    ).migrate(migration_input)

    assert result.status == "FAILED"
    assert result.validation.errors == [
        "Transformation failed while processing the migration."
    ]


def test_analyzer_failure_returns_failed_result(
    migration_input: MigrationInput,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(source_code: str) -> CodeAnalysis:
        del source_code
        raise ValueError("invalid source")

    monkeypatch.setattr(orchestrator.analyzer, "analyze", fail)

    result = orchestrator.MigrationOrchestrator(
        FailingProvider(), tmp_path
    ).migrate(migration_input)

    assert result.status == "FAILED"
    assert any("Analysis failed" in error for error in result.validation.errors)


def test_unsafe_generated_name_fails_before_generation(
    migration_input: MigrationInput,
    metadata: EucMetadata,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        orchestrator.transformer,
        "transform",
        lambda *args: GeneratedEUC(
            name="../outside",
            files=[
                GeneratedFile(path="src/main.py", content="print('ok')\n"),
                GeneratedFile(
                    path="tests/test_main.py",
                    content="def test_ok():\n    assert True\n",
                ),
                GeneratedFile(
                    path="config/config.yaml",
                    content="endpoint: ${ENDPOINT}\n",
                ),
                GeneratedFile(path="requirements.txt", content="requests\n"),
                GeneratedFile(path="README.md", content="# demo\n"),
                GeneratedFile(
                    path="Dockerfile", content="FROM python:3.12-slim\n"
                ),
            ],
            warnings=[],
            unsupported_features=[],
        ),
    )

    result = orchestrator.MigrationOrchestrator(
        FakeProvider(metadata), tmp_path
    ).migrate(migration_input)

    assert result.status == "FAILED"
    assert "outside the output root" in result.validation.errors[0]


def test_existing_symlink_generated_name_cannot_escape_output_root(
    migration_input: MigrationInput,
    metadata: EucMetadata,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    generated_directory = tmp_path / metadata.name
    try:
        generated_directory.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this platform.")

    monkeypatch.setattr(
        orchestrator.transformer,
        "transform",
        lambda *args: GeneratedEUC(
            name=metadata.name,
            files=[
                GeneratedFile(path="src/main.py", content="print('ok')\n"),
                GeneratedFile(
                    path="tests/test_main.py",
                    content="def test_ok():\n    assert True\n",
                ),
                GeneratedFile(
                    path="config/config.yaml",
                    content="endpoint: ${ENDPOINT}\n",
                ),
                GeneratedFile(path="requirements.txt", content="requests\n"),
                GeneratedFile(path="README.md", content="# demo\n"),
                GeneratedFile(
                    path="Dockerfile", content="FROM python:3.12-slim\n"
                ),
            ],
            warnings=[],
            unsupported_features=[],
        ),
    )

    result = orchestrator.MigrationOrchestrator(
        FakeProvider(metadata), tmp_path
    ).migrate(migration_input)

    assert result.status == "FAILED"
    assert "outside the output root" in result.validation.errors[0]
    assert not (outside / "src" / "main.py").exists()

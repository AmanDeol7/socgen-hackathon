"""Application-layer orchestration for synchronous EUC migrations."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import tempfile
from pathlib import Path

from app.schemas.execution import EucExecutionMetadata
from app.schemas.migration import (
    CodeAnalysis,
    GeneratedEUC,
    GeneratedFile,
    MigrationInput,
    MigrationResult,
    ValidationResult,
)
from app.services.execution.registry import EucRegistry
from app.services.migration import (
    analyzer,
    docker_builder,
    generator,
    transformer,
    validator,
)

_STANDARD_SPECIFICATION = (
    Path(__file__).resolve().parents[4] / "docs" / "euc-standard.md"
)
_UNCONFIGURED_PROVIDER_MESSAGE = (
    "No LLM provider is configured for this migration service."
)
_EDITABLE_PATH = re.compile(r"tests/[A-Za-z0-9][A-Za-z0-9._-]*\.py\Z")
logger = logging.getLogger(__name__)


class MigrationOrchestrator:
    """Compose analysis, transformation, validation, and generation."""

    def __init__(
        self,
        provider: transformer.LLMProvider,
        output_root: str | Path,
        standard_specification_path: str | Path = _STANDARD_SPECIFICATION,
        registry: EucRegistry | None = None,
        image_builder: docker_builder.DockerImageBuilder | None = None,
    ) -> None:
        self.provider = provider
        self.output_root = Path(output_root)
        self.standard_specification_path = Path(standard_specification_path)
        self.registry = registry
        self.image_builder = image_builder or docker_builder.DockerImageBuilder()

    def migrate(self, migration_input: MigrationInput) -> MigrationResult:
        """Run a migration and return a contract-shaped result on every path."""
        logger.info("Migration started.")
        try:
            analysis = analyzer.analyze(migration_input.source_code)
        except ValueError as error:
            logger.warning("Migration analysis failed: %s", error)
            return self._failure(migration_input, "analysis", error)

        try:
            specification = self.standard_specification_path.read_text(
                encoding="utf-8"
            )
            generated = transformer.transform(
                migration_input.source_code,
                analysis,
                migration_input.metadata,
                specification,
                self.provider,
            )
        except (OSError, RuntimeError, ValueError) as error:
            logger.warning(
                "Migration transformation failed: %s",
                self._transformation_diagnostic(error),
            )
            return self._failure(migration_input, "transformation", error)

        return self._generate_validate_build_register(
            generated,
            migration_input,
            analysis,
        )

    def create_euc(self, create_input: MigrationInput) -> MigrationResult:
        """Create an EUC from platform-compatible source without LLM transformation."""
        logger.info("Direct EUC creation started.")
        try:
            analysis = analyzer.analyze(create_input.source_code)
        except ValueError as error:
            logger.warning("Direct EUC source analysis failed: %s", error)
            return self._failure(create_input, "analysis", error)

        source_validation = validator.validate_source(analysis)
        if not source_validation.valid:
            generated = GeneratedEUC(
                name=create_input.metadata.name,
                files=[],
                warnings=analysis.warnings,
                unsupported_features=[],
            )
            return MigrationResult(
                status="FAILED",
                generated_euc=generated,
                validation=source_validation,
            )

        generated = GeneratedEUC(
            name=create_input.metadata.name,
            files=[
                GeneratedFile(
                    path="src/main.py",
                    content=create_input.source_code,
                )
            ],
            warnings=analysis.warnings
            or ["Created directly from platform-compatible Python source."],
            unsupported_features=[],
        )
        return self._generate_validate_build_register(
            generated,
            create_input,
            analysis,
            stage_direct_creation=True,
        )

    def edit_euc(
        self,
        name: str,
        editable_files: list[GeneratedFile],
    ) -> EucExecutionMetadata:
        """Validate, build, and atomically replace only an EUC's business files."""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) or name in {
            ".",
            "..",
        }:
            raise ValueError("Invalid EUC name.")
        if self.registry is None:
            raise ValueError("The EUC registry is not configured.")
        try:
            entry = self.registry.get(name)
        except ValueError:
            try:
                self.registry.register_existing(name)
                entry = self.registry.get(name)
            except ValueError as error:
                raise FileNotFoundError("EUC not found.") from error

        root = self.output_root.resolve()
        artifact = Path(entry.path).resolve()
        try:
            artifact.relative_to(root)
        except ValueError as error:
            raise ValueError("EUC path is outside the configured output directory.") from error
        if artifact == root or not artifact.is_dir():
            raise FileNotFoundError("EUC artifact not found.")
        if not editable_files:
            raise ValueError("Provide at least one editable business Python file.")

        edits: dict[str, str] = {}
        for item in editable_files:
            path = item.path
            if path not in {"src/main.py", "src/logic.py"} and not _EDITABLE_PATH.fullmatch(
                path
            ):
                raise ValueError(f"File is not editable: {path!r}.")
            if path == "tests/test_euc_contract.py":
                raise ValueError("The platform-owned EUC contract test cannot be edited.")
            if path in edits:
                raise ValueError(f"Duplicate edited file: {path!r}.")
            edits[path] = item.content

        current_files: list[GeneratedFile] = []
        for path in sorted(artifact.rglob("*")):
            if path.is_symlink():
                raise ValueError("EUC artifact contains an unsafe symbolic link.")
            if not path.is_file():
                continue
            resolved = path.resolve()
            try:
                relative = resolved.relative_to(artifact).as_posix()
                content = resolved.read_text(encoding="utf-8")
            except (OSError, UnicodeError, ValueError) as error:
                raise ValueError("Unable to safely read the existing EUC artifact.") from error
            current_files.append(GeneratedFile(path=relative, content=content))

        files_by_path = {item.path: item.content for item in current_files}
        if "src/main.py" not in files_by_path:
            raise ValueError("The existing EUC is missing src/main.py.")
        meaningful_change = any(files_by_path.get(path) != content for path, content in edits.items())
        candidate_files = [
            GeneratedFile(path=path, content=edits.get(path, content))
            for path, content in files_by_path.items()
        ]
        candidate_files.extend(
            GeneratedFile(path=path, content=content)
            for path, content in edits.items()
            if path not in files_by_path
        )
        candidate = GeneratedEUC(
            name=name,
            files=candidate_files,
            warnings=["Updated through the EUC edit workflow."],
            unsupported_features=[],
        )
        source_validation = validator.validate_source(
            analyzer.analyze(edits.get("src/main.py", files_by_path["src/main.py"]))
        )
        if not source_validation.valid:
            raise ValueError("EUC source validation failed: " + " ".join(source_validation.errors))
        validation = validator.validate(candidate)
        if not validation.valid:
            raise ValueError("EUC validation failed: " + " ".join(validation.errors))
        if not meaningful_change:
            return self.registry.refresh_certification(name)

        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".euc-edit-", dir=root) as temporary:
            temporary_root = Path(temporary)
            staged = temporary_root / name
            backup = temporary_root / "previous"
            generator.generate_euc(candidate, staged)
            self.image_builder.build(staged, entry.image, entry.version)

            artifact.rename(backup)
            try:
                staged.rename(artifact)
            except OSError:
                backup.rename(artifact)
                raise
            try:
                return self.registry.replace_artifact(name, artifact)
            except (OSError, ValueError):
                failed = temporary_root / "failed"
                artifact.rename(failed)
                backup.rename(artifact)
                raise

    def _generate_validate_build_register(
        self,
        generated: GeneratedEUC,
        migration_input: MigrationInput,
        analysis: CodeAnalysis,
        stage_direct_creation: bool = False,
    ) -> MigrationResult:
        """Run deterministic assembly through registration for either entry path."""
        try:
            generated = generator.assemble(
                generated,
                migration_input.metadata,
                analysis,
            )
            validation = validator.validate(generated)
        except (OSError, SyntaxError, ValueError) as error:
            logger.warning("Migration validation failed: %s", error)
            return self._failure(
                migration_input,
                "validation",
                error,
                generated_euc=generated,
            )

        if not validation.valid:
            logger.warning(
                "Migration validation rejected generated EUC: %d error(s), %d warning(s).",
                len(validation.errors),
                len(validation.warnings),
            )
            return MigrationResult(
                status="FAILED",
                generated_euc=generated,
                validation=validation,
            )

        try:
            output_directory = self._output_directory(generated)
            if stage_direct_creation:
                if output_directory.exists() or (
                    self.registry is not None
                    and self.registry.exists(generated.name)
                ):
                    raise ValueError("An EUC with this name already exists.")
                self._build_staged_artifact(generated, output_directory)
            else:
                if self.registry is not None:
                    self.registry.unregister(generated.name)
                generator.generate_euc(generated, output_directory)
        except docker_builder.DockerBuildError as error:
            logger.warning("Docker image build failed: %s", error)
            return self._failure(
                migration_input,
                "docker_build",
                error,
                generated_euc=generated,
                validation=validation,
            )
        except (OSError, RuntimeError, ValueError) as error:
            logger.warning("EUC generation failed: %s", error)
            return self._failure(
                migration_input,
                "generation",
                error,
                generated_euc=generated,
                validation=validation,
            )

        if not stage_direct_creation:
            try:
                self.image_builder.build(output_directory, generated.name, "latest")
            except docker_builder.DockerBuildError as error:
                logger.warning("Docker image build failed: %s", error)
                return self._failure(
                    migration_input,
                    "docker_build",
                    error,
                    generated_euc=generated,
                    validation=validation,
                )

        if self.registry is not None:
            try:
                self.registry.register(
                    EucExecutionMetadata(
                        name=generated.name,
                        image=generated.name,
                        version="latest",
                        path=str(output_directory),
                        owners=migration_input.metadata.owners,
                        certification_metadata_fingerprint=hashlib.sha256(
                            json.dumps(
                                migration_input.metadata.model_dump(mode="json"),
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ).hexdigest(),
                    )
                )
            except (OSError, RuntimeError, ValueError) as error:
                logger.warning("Migration registry registration failed.")
                return self._failure(
                    migration_input,
                    "registration",
                    error,
                    generated_euc=generated,
                    validation=validation,
                )

        logger.info("Migration completed successfully.")
        return MigrationResult(
            status="COMPLETED",
            generated_euc=generated,
            validation=validation,
        )

    def _build_staged_artifact(
        self,
        generated: GeneratedEUC,
        output_directory: Path,
    ) -> None:
        """Build directly-authored artifacts privately before publishing them."""
        root = self.output_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".draft-", dir=root) as temporary_root:
            staged_directory = Path(temporary_root) / generated.name
            generator.generate_euc(generated, staged_directory)
            self.image_builder.build(staged_directory, generated.name, "latest")
            staged_directory.rename(output_directory)

    def _output_directory(self, generated: GeneratedEUC) -> Path:
        """Return a contained output directory derived from the generated name."""
        root = self.output_root.resolve()
        target = (root / generated.name).resolve()
        if target == root:
            raise ValueError("Generated EUC name must identify a child directory.")
        try:
            target.relative_to(root)
        except ValueError as error:
            raise ValueError(
                "Generated EUC name would place files outside the output root."
            ) from error
        return target

    @staticmethod
    def _failure(
        migration_input: MigrationInput,
        stage: str,
        error: Exception,
        generated_euc: GeneratedEUC | None = None,
        validation: ValidationResult | None = None,
    ) -> MigrationResult:
        """Convert a stage exception into the existing result contract."""
        if generated_euc is None:
            generated_euc = GeneratedEUC(
                name=migration_input.metadata.name,
                files=[],
                warnings=[],
                unsupported_features=[],
            )
        if validation is None:
            validation = ValidationResult(
                valid=False,
                errors=[MigrationOrchestrator._failure_message(stage, error)],
                warnings=[],
            )
        else:
            validation = validation.model_copy(
                update={
                    "valid": False,
                    "errors": [
                        MigrationOrchestrator._failure_message(stage, error),
                        *validation.errors,
                    ],
                }
            )
        return MigrationResult(
            status="FAILED",
            generated_euc=generated_euc,
            validation=validation,
        )

    @staticmethod
    def _failure_message(stage: str, error: Exception) -> str:
        """Return useful details only for controlled application failures."""
        if stage == "docker_build" and isinstance(error, docker_builder.DockerBuildError):
            return f"Docker build failed: {error}"
        if (
            stage == "transformation"
            and str(error) == _UNCONFIGURED_PROVIDER_MESSAGE
        ):
            return f"Transformation failed: {_UNCONFIGURED_PROVIDER_MESSAGE}"
        if stage == "analysis" and isinstance(error, ValueError):
            return f"Analysis failed: {error}"
        if stage == "generation" and isinstance(error, ValueError):
            return f"Generation failed: {error}"
        return f"{stage.capitalize()} failed while processing the migration."

    @staticmethod
    def _transformation_diagnostic(error: Exception) -> str:
        """Return a safe diagnostic for server logs without response content."""
        message = str(error)
        known_messages = (
            "No LLM provider is configured for this migration service.",
            "LLM provider returned an empty response.",
            "LLM provider response must be a JSON object.",
            "LLM provider response contains an invalid JSON code fence.",
            "LLM provider response must use a JSON code fence.",
            "Generated EUC name must not be empty.",
            "Generated EUC name must match the supplied metadata name.",
            "Generated EUC must contain at least one file.",
            "Generated EUC is missing required file 'src/main.py'.",
            "OpenRouter request failed while generating the transformation.",
            "OpenRouter returned an invalid generation response.",
            "OpenRouter returned an empty generation.",
        )
        if message in known_messages:
            return message
        if message.startswith("LLM provider response is not valid JSON:"):
            return "LLM provider response is not valid JSON."
        if message.startswith("LLM provider response does not match GeneratedEUC:"):
            return "LLM provider response does not match GeneratedEUC."
        if message.startswith("Generated EUC contains an invalid or duplicate file path:"):
            return "Generated EUC contains an invalid or duplicate file path."
        if message.startswith("Generated EUC contains an unsafe file path:"):
            return "Generated EUC contains an unsafe file path."
        if message.startswith("Generated file ") and "retains" in message:
            return "Generated EUC retains MAXX runtime code."
        return "Transformation failed due to an unexpected application error."


class UnconfiguredLLMProvider:
    """Prevent accidental external LLM calls when no provider is configured."""

    def generate(self, prompt: str) -> str:
        """Fail explicitly because this MVP does not configure an LLM."""
        del prompt
        raise transformer.TransformationError(_UNCONFIGURED_PROVIDER_MESSAGE)

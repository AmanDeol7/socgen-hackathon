"""Application-layer orchestration for synchronous EUC migrations."""

from __future__ import annotations

import logging
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

"""Application-layer orchestration for synchronous EUC migrations."""

from __future__ import annotations

import logging
from pathlib import Path

from app.schemas.execution import EucExecutionMetadata
from app.schemas.migration import (
    GeneratedEUC,
    MigrationInput,
    MigrationResult,
    ValidationResult,
)
from app.services.execution.registry import EucRegistry
from app.services.migration import analyzer, generator, transformer, validator

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
    ) -> None:
        self.provider = provider
        self.output_root = Path(output_root)
        self.standard_specification_path = Path(standard_specification_path)
        self.registry = registry

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

        try:
            generated = generator.assemble(generated, migration_input.metadata, analysis)
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
            generator.generate_euc(generated, output_directory)
            if self.registry is not None:
                self.registry.register(
                    EucExecutionMetadata(
                        name=generated.name,
                        image=generated.name,
                        version="latest",
                        path=str(output_directory),
                    )
                )
        except (OSError, RuntimeError, ValueError) as error:
            logger.warning("Migration generation failed: %s", error)
            return self._failure(
                migration_input,
                "generation",
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

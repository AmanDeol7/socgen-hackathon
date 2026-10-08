"""LLM-assisted semantic transformation of MAXX EUCs."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Protocol

from pydantic import ValidationError

from app.schemas.migration import CodeAnalysis, EucMetadata, GeneratedEUC


class LLMProvider(Protocol):
    """Minimal provider interface required by the transformation stage."""

    def generate(self, prompt: str) -> str:
        """Generate a structured transformation response for ``prompt``."""


class TransformationError(ValueError):
    """Raised when a transformation response is unsafe or malformed."""


def transform(
    source_code: str,
    analysis: CodeAnalysis,
    metadata: EucMetadata,
    standard_specification: str,
    provider: LLMProvider,
) -> GeneratedEUC:
    """Transform MAXX source into a validated standardized EUC.

    The provider is injected so transformation can be tested without network
    calls or a concrete commercial LLM SDK.
    """
    prompt = _build_prompt(source_code, analysis, metadata, standard_specification)
    response = provider.generate(prompt)
    generated = _parse_response(response)
    _validate_generated_euc(generated, metadata)
    return generated


def _build_prompt(
    source_code: str,
    analysis: CodeAnalysis,
    metadata: EucMetadata,
    standard_specification: str,
) -> str:
    """Build a complete, explicit transformation request."""
    return f"""You are transforming an existing MAXX EUC, not rewriting it from scratch.

Preserve business logic, external API behavior, authentication and token
generation behavior, error handling, email notification behavior, and useful
logging. Remove MAXX-specific runtime dependencies, including all imports from
sglambdautils. Replace get_lambda_secret(...) with safe secret-reference or
configuration representations. Never include actual secret values or invent
credentials, external APIs, business requirements, or metadata. Do not change
the manually supplied metadata. Generate testable Python and separate business
logic from src/main.py where practical.

Generate the standardized EUC files: src/main.py, appropriate logic and tests,
requirements.txt, config/config.yaml where appropriate, README.md, and
Dockerfile. Report anything that cannot be safely transformed as an
unsupported feature and prefer explicit warnings over guessing.

Return ONLY a JSON object with this shape:
{{
  "name": "the supplied metadata name",
  "files": [{{"path": "src/main.py", "content": "..."}}],
  "warnings": ["..."],
  "unsupported_features": ["..."]
}}

ORIGINAL MAXX SOURCE:
<source>
{source_code}
</source>

DETERMINISTIC CODE ANALYSIS:
{analysis.model_dump_json(indent=2)}

SUPPLIED EUC METADATA:
{metadata.model_dump_json(indent=2)}

STANDARD EUC SPECIFICATION:
<specification>
{standard_specification}
</specification>
"""


def _parse_response(response: str) -> GeneratedEUC:
    """Parse and validate the provider's JSON response."""
    if not isinstance(response, str) or not response.strip():
        raise TransformationError("LLM provider returned an empty response.")

    payload_text = response.strip()
    if payload_text.startswith("```"):
        payload_text = _extract_fenced_json(payload_text)

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as error:
        raise TransformationError(
            f"LLM provider response is not valid JSON: {error.msg}."
        ) from error

    if not isinstance(payload, dict):
        raise TransformationError("LLM provider response must be a JSON object.")

    try:
        return GeneratedEUC.model_validate(payload)
    except ValidationError as error:
        raise TransformationError(
            f"LLM provider response does not match GeneratedEUC: {error}"
        ) from error


def _extract_fenced_json(response: str) -> str:
    """Extract one JSON code fence without accepting surrounding prose."""
    lines = response.splitlines()
    if len(lines) < 3 or not lines[0].startswith("```") or lines[-1].strip() != "```":
        raise TransformationError(
            "LLM provider response contains an invalid JSON code fence."
        )
    if lines[0].strip() not in {"```", "```json"}:
        raise TransformationError("LLM provider response must use a JSON code fence.")
    return "\n".join(lines[1:-1]).strip()


def _validate_generated_euc(generated: GeneratedEUC, metadata: EucMetadata) -> None:
    """Reject incomplete files and MAXX runtime leakage."""
    if not generated.name:
        raise TransformationError("Generated EUC name must not be empty.")
    if generated.name != metadata.name:
        raise TransformationError(
            "Generated EUC name must match the supplied metadata name."
        )
    if not generated.files:
        raise TransformationError("Generated EUC must contain at least one file.")

    paths: set[str] = set()
    for generated_file in generated.files:
        path = generated_file.path
        if not path or path in paths:
            raise TransformationError(
                f"Generated EUC contains an invalid or duplicate file path: {path!r}."
            )
        if not _is_safe_relative_path(path):
            raise TransformationError(f"Generated EUC contains an unsafe file path: {path!r}.")
        paths.add(path)

        if "get_lambda_secret(" in generated_file.content:
            raise TransformationError(
                f"Generated file {path!r} retains get_lambda_secret()."
            )
        if "sglambdautils" in generated_file.content:
            raise TransformationError(
                f"Generated file {path!r} retains MAXX sglambdautils runtime code."
            )

    if "src/main.py" not in paths:
        raise TransformationError("Generated EUC is missing required file 'src/main.py'.")


def _is_safe_relative_path(path: str) -> bool:
    """Allow only normalized, workspace-relative POSIX paths."""
    pure_path = PurePosixPath(path)
    return (
        not pure_path.is_absolute()
        and path == pure_path.as_posix()
        and ".." not in pure_path.parts
    )

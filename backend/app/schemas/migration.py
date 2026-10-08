"""Shared contracts for MAXX EUC migration."""

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class SecretReference(BaseModel):
    """Reference to a secret stored outside the source code."""

    name: str
    vault: str
    key: str


class EucMetadata(BaseModel):
    """Metadata describing an EUC and its operational ownership."""

    name: str
    description: str | None = None
    python_version: str = "3.12"
    owner_team: str
    support_team: str
    schedule: str | None = None
    sharepoint_url: HttpUrl | None = None
    secret_references: list[SecretReference] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)


class MigrationInput(BaseModel):
    """Input payload for a future migration request."""

    metadata: EucMetadata
    source_code: str
    source_filename: str = "main.py"


class FunctionInfo(BaseModel):
    """Details about a function discovered during analysis."""

    name: str
    arguments: list[str]
    line_start: int
    line_end: int


class CodeAnalysis(BaseModel):
    """Deterministic analysis results for a Python source file."""

    imports: list[str]
    functions: list[FunctionInfo]
    entrypoint: str | None
    maxx_imports: list[str]
    secret_usages: list[str]
    external_urls: list[str]
    warnings: list[str]


class GeneratedFile(BaseModel):
    """A file produced as part of a standardized EUC."""

    path: str
    content: str


class GeneratedEUC(BaseModel):
    """Generated standardized EUC files and migration warnings."""

    name: str
    files: list[GeneratedFile]
    warnings: list[str]
    unsupported_features: list[str]


class ValidationResult(BaseModel):
    """Structural and safety validation result."""

    valid: bool
    errors: list[str]
    warnings: list[str]


class MigrationResult(BaseModel):
    """Result of a future migration workflow."""

    status: Literal[
        "ANALYZING",
        "TRANSFORMING",
        "VALIDATING",
        "COMPLETED",
        "FAILED",
    ]
    generated_euc: GeneratedEUC
    validation: ValidationResult

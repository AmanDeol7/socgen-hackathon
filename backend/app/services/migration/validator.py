"""Deterministic structural and safety validation for standardized EUCs."""

from __future__ import annotations

import ast
import re
from pathlib import Path, PurePosixPath

from app.schemas.migration import GeneratedEUC, GeneratedFile, ValidationResult

_REQUIRED_FILES = (
    "src/main.py",
    "config/config.yaml",
    "requirements.txt",
    "README.md",
    "Dockerfile",
)
_SECRET_ASSIGNMENT = re.compile(
    r"""(?im)^\s*
    (?:[A-Za-z_][A-Za-z0-9_]*(?:secret|password|token|api[_-]?key)
    |secret|password|token|api[_-]?key)
    \s*=\s*(['"])
    (?!\s*(?:None|os\.environ|environ\.get|getenv|<[^>]+>|
    \$\{[^}]+\}|your[-_ ]|replace[-_ ]))
    [^'"]+\1""",
    re.VERBOSE,
)


def validate(generated_euc: GeneratedEUC) -> ValidationResult:
    """Validate generated content without importing or executing Python."""
    errors: list[str] = []
    warnings: list[str] = []
    paths: list[str] = []
    seen: set[str] = set()

    contents_by_path: dict[str, str] = {}
    for generated_file in generated_euc.files:
        path = generated_file.path
        paths.append(path)
        contents_by_path.setdefault(path, generated_file.content)
        if not path:
            errors.append("Generated file path is empty.")
            continue
        pure = PurePosixPath(path)
        if (
            pure.is_absolute()
            or path != pure.as_posix()
            or "\\" in path
            or ".." in pure.parts
        ):
            errors.append(f"Unsafe file path: {path!r}. Use a normalized relative POSIX path.")
        if path in seen:
            errors.append(f"Duplicate file path: {path!r}.")
        seen.add(path)

        if path.endswith(".py"):
            try:
                ast.parse(generated_file.content, filename=path)
            except SyntaxError as error:
                errors.append(
                    f"Python syntax error in {path} at line {error.lineno}: {error.msg}."
                )
        if (
            "sglambdautils" in generated_file.content
            or "get_lambda_secret(" in generated_file.content
        ):
            errors.append(f"MAXX runtime dependency leakage in {path}.")
        if _SECRET_ASSIGNMENT.search(generated_file.content):
            errors.append(f"Possible hardcoded secret in {path}; use an environment or secret reference.")

    present = set(paths)
    for required in _REQUIRED_FILES:
        if required not in present:
            errors.append(f"Missing required file: {required}.")
        elif not contents_by_path[required].strip():
            errors.append(f"Required file '{required}' is empty.")
    if not any(path.startswith("tests/") and path.endswith(".py") for path in present):
        errors.append("Missing required test file under tests/.")
    if "src/logic.py" not in present:
        warnings.append("src/logic.py is absent; keep business logic separate where practical.")
    if not generated_euc.warnings:
        warnings.append("No transformation warnings were supplied.")
    warnings.extend(generated_euc.warnings)
    return ValidationResult(valid=not errors, errors=_unique(errors), warnings=_unique(warnings))


def validate_directory(directory: str | Path) -> ValidationResult:
    """Validate an already materialised EUC without executing its contents."""
    root = Path(directory)
    if not root.is_dir():
        return ValidationResult(valid=False, errors=[f"EUC directory does not exist: {root}."], warnings=[])
    files = [
        GeneratedFile(path=file.relative_to(root).as_posix(), content=file.read_text(encoding="utf-8"))
        for file in sorted(root.rglob("*"))
        if file.is_file()
    ]
    return validate(GeneratedEUC(name=root.name, files=files, warnings=[], unsupported_features=[]))


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))

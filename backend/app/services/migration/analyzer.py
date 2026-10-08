"""Deterministic static analysis for MAXX EUC Python source code."""

from __future__ import annotations

import ast
import re

from app.schemas.migration import CodeAnalysis, FunctionInfo

_MAXX_IMPORT_PREFIX = "sglambdautils"
_URL_PATTERN = re.compile(r"https?://[^\s\"']+")
_SECRET_FUNCTION_NAME = "get_lambda_secret"
_SUSPICIOUS_CALLS = frozenset({"eval", "exec", "__import__"})


def analyze(source_code: str) -> CodeAnalysis:
    """Analyze Python source without importing or executing it.

    Args:
        source_code: Python source text to inspect.

    Raises:
        ValueError: If ``source_code`` is not valid Python.
    """
    try:
        tree = ast.parse(source_code)
    except SyntaxError as error:
        location = f"line {error.lineno}, column {error.offset}"
        detail = error.msg or "invalid syntax"
        raise ValueError(f"Unable to parse Python source at {location}: {detail}") from error

    imports: list[str] = []
    maxx_imports: list[str] = []
    functions: list[FunctionInfo] = []
    secret_usages: list[str] = []
    external_urls: list[str] = []
    warnings: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
                if alias.name.startswith(_MAXX_IMPORT_PREFIX):
                    maxx_imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            imports.append(node.module)
            if node.module.startswith(_MAXX_IMPORT_PREFIX):
                maxx_imports.append(node.module)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(_function_info(node))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            external_urls.extend(_URL_PATTERN.findall(node.value))
        elif isinstance(node, ast.Call):
            _inspect_call(node, secret_usages, warnings)

    functions.sort(key=lambda function: (function.line_start, function.name))
    entrypoint = "run" if any(function.name == "run" for function in functions) else None

    return CodeAnalysis(
        imports=_unique(imports),
        functions=functions,
        entrypoint=entrypoint,
        maxx_imports=_unique(maxx_imports),
        secret_usages=_unique(secret_usages),
        external_urls=_unique(external_urls),
        warnings=_unique(warnings),
    )


def _function_info(node: ast.FunctionDef | ast.AsyncFunctionDef) -> FunctionInfo:
    """Convert a function AST node into the shared analysis model."""
    arguments = [
        argument.arg
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
        )
    ]
    if node.args.vararg is not None:
        arguments.append(node.args.vararg.arg)
    arguments.extend(argument.arg for argument in node.args.kwonlyargs)
    if node.args.kwarg is not None:
        arguments.append(node.args.kwarg.arg)

    return FunctionInfo(
        name=node.name,
        arguments=arguments,
        line_start=node.lineno,
        line_end=node.end_lineno or node.lineno,
    )


def _inspect_call(
    node: ast.Call,
    secret_usages: list[str],
    warnings: list[str],
) -> None:
    """Collect secret calls and suspicious dynamic constructs."""
    function_name = _called_name(node.func)
    if function_name == _SECRET_FUNCTION_NAME:
        if node.args and isinstance(node.args[0], ast.Constant):
            secret_name = node.args[0].value
            if isinstance(secret_name, str):
                secret_usages.append(secret_name)
            else:
                warnings.append(
                    "get_lambda_secret() has a non-string secret name at "
                    f"line {node.lineno}."
                )
        else:
            warnings.append(
                "get_lambda_secret() has a dynamically determined secret name "
                f"at line {node.lineno}."
            )

    if function_name in _SUSPICIOUS_CALLS:
        warnings.append(
            f"Suspicious dynamic operation {function_name}() at line {node.lineno}."
        )


def _called_name(node: ast.expr) -> str | None:
    """Return the final name in a call target, when one is available."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _unique(values: list[str]) -> list[str]:
    """Deduplicate values while preserving source traversal order."""
    return list(dict.fromkeys(values))

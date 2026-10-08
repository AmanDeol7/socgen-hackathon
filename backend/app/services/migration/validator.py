"""Deterministic structural and safety validation for standardized EUCs."""

from __future__ import annotations

import ast
import builtins
import re
from pathlib import Path, PurePosixPath

from app.schemas.migration import GeneratedEUC, GeneratedFile, ValidationResult

_BUILTINS = set(dir(builtins))

_REQUIRED_FILES = (
    "src/main.py",
    "src/runner.py",
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
                tree = ast.parse(generated_file.content, filename=path)
            except SyntaxError as error:
                errors.append(
                    f"Python syntax error in {path} at line {error.lineno}: {error.msg}."
                )
            else:
                errors.extend(
                    f"Undefined name '{name}' in {path} at line {line}."
                    for name, line in _undefined_names(tree)
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


class _Scope:
    def __init__(self, parent: _Scope | None = None) -> None:
        self.parent = parent
        self.bound: set[str] = set()
        self.loads: list[tuple[str, int]] = []

    def resolves(self, name: str) -> bool:
        return name in self.bound or (
            self.parent is not None and self.parent.resolves(name)
        )


class _NameAnalyzer(ast.NodeVisitor):
    def __init__(self) -> None:
        self.module = _Scope()
        self.scope = self.module
        self.scopes: list[_Scope] = [self.module]

    def visit_Module(self, node: ast.Module) -> None:
        self.scope.bound.update(_bindings(node.body))
        for item in node.body:
            self.visit(item)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.scope.loads.append((node.id, node.lineno))
        else:
            self.scope.bound.add(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.scope.bound.add(alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name != "*":
                self.scope.bound.add(alias.asname or alias.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.bound.add(node.name)
        self._visit_function_expressions(node)
        self._visit_function(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.bound.add(node.name)
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        self._visit_nested(node, node.body)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_nested(node, [node.body], node.args)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._visit_nested(node, node.body, node.args)

    def _visit_function_expressions(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            if argument.annotation:
                self.visit(argument.annotation)
        if node.args.vararg and node.args.vararg.annotation:
            self.visit(node.args.vararg.annotation)
        if node.args.kwarg and node.args.kwarg.annotation:
            self.visit(node.args.kwarg.annotation)
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default:
                self.visit(default)
        if node.returns:
            self.visit(node.returns)

    def _visit_nested(
        self,
        node: ast.AST,
        body: list[ast.stmt | ast.expr],
        arguments: ast.arguments | None = None,
    ) -> None:
        parent = self.scope
        child = _Scope(parent)
        self.scopes.append(child)
        self.scope = child
        child.bound.update(_bindings(body))
        if arguments is not None:
            for argument in (
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
            ):
                child.bound.add(argument.arg)
            if arguments.vararg:
                child.bound.add(arguments.vararg.arg)
            if arguments.kwarg:
                child.bound.add(arguments.kwarg.arg)
        for item in body:
            self.visit(item)
        self.scope = parent


def _undefined_names(tree: ast.AST) -> list[tuple[str, int]]:
    """Return unresolved lexical names without importing or executing code."""
    analyzer = _NameAnalyzer()
    analyzer.visit(tree)
    undefined: list[tuple[str, int]] = []
    for scope in analyzer.scopes:
        for name, line in scope.loads:
            if name not in _BUILTINS and not scope.resolves(name):
                undefined.append((name, line))
    return sorted(set(undefined), key=lambda item: (item[1], item[0]))


class _BindingCollector(ast.NodeVisitor):
    """Collect bindings in one lexical scope without entering nested scopes."""

    def __init__(self) -> None:
        self.bound: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.bound.add(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.bound.add(alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name != "*":
                self.bound.add(alias.asname or alias.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.bound.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.bound.add(node.name)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.bound.add(node.name)
        if node.type:
            self.visit(node.type)
        for statement in node.body:
            self.visit(statement)


def _bindings(body: list[ast.stmt | ast.expr]) -> set[str]:
    collector = _BindingCollector()
    for item in body:
        collector.visit(item)
    return collector.bound

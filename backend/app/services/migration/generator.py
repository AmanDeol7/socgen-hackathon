"""Deterministic, safe materialisation of generated EUC files."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from app.schemas.migration import GeneratedEUC


def generate(generated_euc: GeneratedEUC, output_dir: str | Path) -> list[Path]:
    """Write an EUC below ``output_dir`` and return paths in input order.

    All paths are checked before any file is created.  This prevents a malformed
    response from producing a partially written EUC.
    """
    paths = _validated_paths(generated_euc)
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    targets = _resolved_targets(destination, paths)
    written: list[Path] = []
    for generated_file, target in zip(generated_euc.files, targets):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(generated_file.content, encoding="utf-8", newline="")
        written.append(target)
    return written


def generate_euc(generated_euc: GeneratedEUC, output_dir: str | Path) -> list[Path]:
    """Descriptive alias for :func:`generate`."""
    return generate(generated_euc, output_dir)


def _validated_paths(generated_euc: GeneratedEUC) -> list[PurePosixPath]:
    seen: set[str] = set()
    validated: list[PurePosixPath] = []
    for generated_file in generated_euc.files:
        path = generated_file.path
        if not path:
            raise ValueError("Generated EUC contains an empty file path.")
        pure = PurePosixPath(path)
        if (
            pure.is_absolute()
            or path != pure.as_posix()
            or ".." in pure.parts
            or "\\" in path
            or not pure.parts
        ):
            raise ValueError(f"Generated EUC contains an unsafe file path: {path!r}.")
        if path in seen:
            raise ValueError(f"Generated EUC contains a duplicate file path: {path!r}.")
        seen.add(path)
        validated.append(pure)
    return validated


def _resolved_targets(
    destination: Path, paths: list[PurePosixPath]
) -> list[Path]:
    """Resolve targets and reject symlink or traversal escapes."""
    targets: list[Path] = []
    for relative in paths:
        target = destination.joinpath(*relative.parts).resolve()
        try:
            target.relative_to(destination)
        except ValueError as error:
            raise ValueError(
                f"Generated EUC path escapes the destination: {relative.as_posix()!r}."
            ) from error
        targets.append(target)
    return targets

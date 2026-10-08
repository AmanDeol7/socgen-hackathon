"""Small in-memory registry for local standardized EUC artifacts."""

from __future__ import annotations

import re
from pathlib import Path

from app.schemas.execution import EucExecutionMetadata

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class RegistryError(ValueError):
    """Base error for invalid registry operations."""


class DuplicateEucError(RegistryError):
    """Raised when an EUC name is already registered."""


class EucNotFoundError(RegistryError):
    """Raised when a logical EUC name is not registered."""


class EucRegistry:
    """Authoritative in-memory mapping from logical name to execution metadata."""

    def __init__(self, output_root: str | Path) -> None:
        self.output_root = Path(output_root).resolve()
        self._entries: dict[str, EucExecutionMetadata] = {}
        self._github_entries: dict[str, dict[str, str]] = {}

    def register(self, euc: EucExecutionMetadata) -> None:
        """Register one validated executable artifact."""
        _validate_identifier(euc.name, "EUC name")
        _validate_identifier(euc.image, "Docker image")
        _validate_identifier(euc.version, "EUC version")
        path = Path(euc.path).resolve()
        try:
            path.relative_to(self.output_root)
        except ValueError as error:
            raise RegistryError("EUC path must remain inside the output root.") from error
        if path == self.output_root or not path.is_dir() or not (path / "Dockerfile").is_file():
            raise RegistryError("EUC artifact path is invalid.")
        if euc.name in self._entries:
            raise DuplicateEucError(f"EUC '{euc.name}' is already registered.")
        self._entries[euc.name] = euc.model_copy(update={"path": str(path)})

    def get(self, name: str) -> EucExecutionMetadata:
        """Return metadata for a registered EUC."""
        _validate_identifier(name, "EUC name")
        try:
            return self._entries[name]
        except KeyError as error:
            raise EucNotFoundError(f"EUC '{name}' was not found.") from error

    def exists(self, name: str) -> bool:
        """Return whether a logical EUC name is registered."""
        try:
            return name in self._entries if _validate_identifier(name, "EUC name", False) else False
        except RegistryError:
            return False

    def unregister(self, name: str) -> bool:
        """Remove a registered artifact before replacing its materialized files."""
        _validate_identifier(name, "EUC name")
        return self._entries.pop(name, None) is not None

    def update_github(
        self,
        name: str,
        repository: str,
        url: str,
        commit_sha: str,
    ) -> None:
        """Store optional GitHub metadata for an already registered EUC."""
        _validate_identifier(name, "EUC name")
        self._github_entries[name] = {
            "github_repo": repository,
            "github_url": url,
            "github_commit_sha": commit_sha,
        }
        try:
            entry = self.get(name)
        except EucNotFoundError:
            return
        self._entries[name] = entry.model_copy(
            update=self._github_entries[name]
        )

    def github_metadata(self, name: str) -> dict[str, str | None]:
        """Return optional process-local GitHub metadata for an EUC."""
        return self._github_entries.get(
            name,
            {
                "github_repo": None,
                "github_url": None,
                "github_commit_sha": None,
            },
        )

    def list(self) -> list[EucExecutionMetadata]:
        """Return registered entries in deterministic name order."""
        return [self._entries[name] for name in sorted(self._entries)]

    def register_existing(self, name: str) -> None:
        """Register an existing generated EUC using deterministic local defaults."""
        path = (self.output_root / name).resolve()
        if not path.is_dir() or not (path / "Dockerfile").is_file():
            raise EucNotFoundError(f"EUC '{name}' was not found.")
        self.register(
            EucExecutionMetadata(
                name=name,
                image=name,
                version="latest",
                path=str(path),
            )
        )


_REGISTRIES: dict[str, EucRegistry] = {}


def get_registry(output_root: str | Path) -> EucRegistry:
    """Return the process-local registry for an output root."""
    key = str(Path(output_root).resolve())
    if key not in _REGISTRIES:
        _REGISTRIES[key] = EucRegistry(key)
    return _REGISTRIES[key]


def _validate_identifier(value: str, label: str, raise_error: bool = True) -> bool:
    valid = bool(_SAFE_IDENTIFIER.fullmatch(value)) and value not in {".", ".."}
    if not valid and raise_error:
        raise RegistryError(f"Invalid {label}.")
    return valid

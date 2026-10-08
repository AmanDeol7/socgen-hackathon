"""Small in-memory registry for local standardized EUC artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from app.schemas.execution import EucExecutionMetadata

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REGISTRY_FILENAME = ".euc-registry.json"


class RegistryError(ValueError):
    """Base error for invalid registry operations."""


class DuplicateEucError(RegistryError):
    """Raised when an EUC name is already registered."""


class EucNotFoundError(RegistryError):
    """Raised when a logical EUC name is not registered."""


class CertificationOwnerError(RegistryError):
    """Raised when a certification action is requested by a non-owner."""


class CertificationStateError(RegistryError):
    """Raised when a certification transition is not allowed."""


class CertificationMetadataError(RegistryError):
    """Raised when an EUC cannot be certified with its current metadata."""


class EucRegistry:
    """Authoritative in-memory mapping from logical name to execution metadata."""

    def __init__(self, output_root: str | Path) -> None:
        self.output_root = Path(output_root).resolve()
        self._entries: dict[str, EucExecutionMetadata] = {}
        self._github_entries: dict[str, dict[str, str]] = {}
        self._registry_path = self.output_root / _REGISTRY_FILENAME
        self._load()

    def _load(self) -> None:
        """Load persisted metadata, including ownership, for existing artifacts."""
        if not self._registry_path.exists():
            return
        try:
            payload = json.loads(self._registry_path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise TypeError("Registry data must be a JSON array.")
            for item in payload:
                entry = EucExecutionMetadata.model_validate(item)
                _validate_identifier(entry.name, "EUC name")
                _validate_identifier(entry.image, "Docker image")
                _validate_identifier(entry.version, "EUC version")
                path = Path(entry.path).resolve()
                path.relative_to(self.output_root)
                if (
                    path == self.output_root
                    or not path.is_dir()
                    or not (path / "Dockerfile").is_file()
                    or entry.name in self._entries
                ):
                    raise ValueError("Registry entry does not identify a valid EUC.")
                normalized = entry.model_copy(update={"path": str(path)})
                self._entries[entry.name] = normalized
                github_fields = {
                    key: value
                    for key, value in {
                        "github_repo": normalized.github_repo,
                        "github_url": normalized.github_url,
                        "github_commit_sha": normalized.github_commit_sha,
                    }.items()
                    if value is not None
                }
                if github_fields:
                    self._github_entries[entry.name] = github_fields
        except (OSError, TypeError, ValueError, ValidationError) as error:
            self._entries.clear()
            self._github_entries.clear()
            raise RegistryError(
                f"Unable to load persisted EUC registry at {self._registry_path}."
            ) from error

    def _persist(self, entries: dict[str, EucExecutionMetadata]) -> None:
        """Atomically save local registry metadata as JSON."""
        temporary_path: str | None = None
        try:
            self.output_root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.output_root,
                prefix=".euc-registry-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = temporary.name
                json.dump(
                    [
                        entries[name].model_dump(mode="json")
                        for name in sorted(entries)
                    ],
                    temporary,
                    indent=2,
                    sort_keys=True,
                )
                temporary.write("\n")
            os.replace(temporary_path, self._registry_path)
        except OSError as error:
            raise RegistryError("Unable to persist the local EUC registry.") from error
        finally:
            if temporary_path is not None:
                Path(temporary_path).unlink(missing_ok=True)

    def _store_entry(self, entry: EucExecutionMetadata) -> None:
        """Persist an updated entry before making it visible in memory."""
        updated_entries = self._entries.copy()
        updated_entries[entry.name] = entry
        self._persist(updated_entries)
        self._entries = updated_entries
        github_fields = {
            key: value
            for key, value in {
                "github_repo": entry.github_repo,
                "github_url": entry.github_url,
                "github_commit_sha": entry.github_commit_sha,
            }.items()
            if value is not None
        }
        if github_fields:
            self._github_entries[entry.name] = github_fields
        else:
            self._github_entries.pop(entry.name, None)

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
        self._store_entry(euc.model_copy(update={"path": str(path)}))

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
        if name not in self._entries:
            return False
        updated_entries = self._entries.copy()
        del updated_entries[name]
        self._persist(updated_entries)
        self._entries = updated_entries
        self._github_entries.pop(name, None)
        return True

    def replace_artifact(self, name: str, path: str | Path) -> EucExecutionMetadata:
        """Point an existing registry entry at its successfully replaced artifact."""
        entry = self.get(name)
        resolved = Path(path).resolve()
        try:
            resolved.relative_to(self.output_root)
        except ValueError as error:
            raise RegistryError("EUC path must remain inside the output root.") from error
        if (
            resolved == self.output_root
            or not resolved.is_dir()
            or not (resolved / "Dockerfile").is_file()
        ):
            raise RegistryError("EUC artifact path is invalid.")

        update: dict[str, str | None] = {"path": str(resolved)}
        if entry.certification_status == "CERTIFIED":
            update.update(
                {
                    "certification_status": "PENDING_APPROVAL",
                    "approved_by": None,
                    "approved_at": None,
                    "rejected_by": None,
                    "rejected_at": None,
                    "rejection_reason": None,
                }
            )
        replacement = entry.model_copy(update=update)
        replacement = replacement.model_copy(
            update={"certification_fingerprint": self._current_fingerprint(replacement)}
        )
        self._store_entry(replacement)
        return replacement

    def update_github(
        self,
        name: str,
        repository: str,
        url: str,
        commit_sha: str,
    ) -> None:
        """Store optional GitHub metadata for an already registered EUC."""
        _validate_identifier(name, "EUC name")
        try:
            entry = self.get(name)
        except EucNotFoundError:
            self._github_entries[name] = {
                "github_repo": repository,
                "github_url": url,
                "github_commit_sha": commit_sha,
            }
            return
        self._store_entry(
            entry.model_copy(
                update={
                    "github_repo": repository,
                    "github_url": url,
                    "github_commit_sha": commit_sha,
                }
            )
        )

    def submit_for_certification(self, name: str) -> EucExecutionMetadata:
        """Submit a validly owned EUC for approval, clearing any old decision."""
        entry = self.refresh_certification(name)
        if not entry.owners:
            raise CertificationMetadataError(
                "EUC must have at least one owner before certification."
            )
        if entry.certification_status == "CERTIFIED":
            raise CertificationStateError(
                "A certified EUC cannot be submitted again without a content change."
            )
        updated = entry.model_copy(
            update={
                "certification_status": "PENDING_APPROVAL",
                "approved_by": None,
                "approved_at": None,
                "rejected_by": None,
                "rejected_at": None,
                "rejection_reason": None,
                "certification_fingerprint": self._current_fingerprint(entry),
            }
        )
        self._store_entry(updated)
        return updated

    def approve(self, name: str, owner_email: str) -> EucExecutionMetadata:
        """Approve a pending EUC when the supplied email is one of its owners."""
        entry = self._pending_owner_entry(name, owner_email)
        current_fingerprint = self._current_fingerprint(entry)
        if entry.certification_fingerprint != current_fingerprint:
            raise CertificationStateError(
                "EUC content changed after submission; submit it again before approval."
            )
        updated = entry.model_copy(
            update={
                "certification_status": "CERTIFIED",
                "approved_by": owner_email,
                "approved_at": datetime.now(UTC).isoformat(),
                "rejected_by": None,
                "rejected_at": None,
                "rejection_reason": None,
                "certification_fingerprint": current_fingerprint,
            }
        )
        self._store_entry(updated)
        return updated

    def reject(
        self,
        name: str,
        owner_email: str,
        reason: str | None = None,
    ) -> EucExecutionMetadata:
        """Reject a pending EUC when the supplied email is one of its owners."""
        entry = self._pending_owner_entry(name, owner_email)
        updated = entry.model_copy(
            update={
                "certification_status": "REJECTED",
                "approved_by": None,
                "approved_at": None,
                "rejected_by": owner_email,
                "rejected_at": datetime.now(UTC).isoformat(),
                "rejection_reason": reason,
                "certification_fingerprint": None,
            }
        )
        self._store_entry(updated)
        return updated

    def refresh_certification(self, name: str) -> EucExecutionMetadata:
        """Invalidate approval if generated files or registered metadata changed."""
        entry = self.get(name)
        if entry.certification_status != "CERTIFIED":
            return entry
        current_fingerprint = self._current_fingerprint(entry)
        if entry.certification_fingerprint == current_fingerprint:
            return entry
        updated = entry.model_copy(
            update={
                "certification_status": "PENDING_APPROVAL",
                "approved_by": None,
                "approved_at": None,
                "rejected_by": None,
                "rejected_at": None,
                "rejection_reason": None,
                "certification_fingerprint": current_fingerprint,
            }
        )
        self._store_entry(updated)
        return updated

    def _pending_owner_entry(
        self,
        name: str,
        owner_email: str,
    ) -> EucExecutionMetadata:
        entry = self.get(name)
        if owner_email not in entry.owners:
            raise CertificationOwnerError(
                "Only an owner listed for this EUC may approve or reject it."
            )
        if entry.certification_status != "PENDING_APPROVAL":
            raise CertificationStateError(
                "EUC must be pending approval before an owner decision."
            )
        return entry

    def _current_fingerprint(self, entry: EucExecutionMetadata) -> str:
        root = Path(entry.path).resolve()
        try:
            root.relative_to(self.output_root)
        except ValueError as error:
            raise CertificationMetadataError(
                "Generated EUC path is outside the configured output directory."
            ) from error
        if root == self.output_root or not root.is_dir():
            raise CertificationMetadataError(
                "Generated EUC directory is unavailable for certification."
            )
        digest = hashlib.sha256()
        digest.update(
            json.dumps(
                {
                    "owners": entry.owners,
                    "metadata": entry.certification_metadata_fingerprint,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        try:
            paths = sorted(root.rglob("*"))
            for path in paths:
                if not path.is_file():
                    continue
                resolved = path.resolve()
                resolved.relative_to(root)
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(resolved.read_bytes())
                digest.update(b"\0")
        except (OSError, ValueError) as error:
            raise CertificationMetadataError(
                "Unable to verify the generated EUC content for certification."
            ) from error
        return digest.hexdigest()

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

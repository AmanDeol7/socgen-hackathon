"""Small GitHub REST client for saving generated EUC artifacts."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_API_ROOT = "https://api.github.com"


class GitHubConfigurationError(ValueError):
    """Raised when required GitHub environment configuration is missing."""


class GitHubSaveError(ValueError):
    """Raised when the GitHub repository or commit operation fails."""


class GitHubService:
    """Create/reuse an organization repository and commit generated files."""

    def __init__(
        self,
        organization: str | None = None,
        token: str | None = None,
        http_open: Callable[..., object] = urlopen,
    ) -> None:
        self.organization = organization or os.getenv("GITHUB_ORG")
        self.token = token or os.getenv("GITHUB_TOKEN")
        self._http_open = http_open

    def save(self, euc_name: str, directory: str | Path) -> dict[str, str]:
        """Save the full standardized artifact as one normal Git commit."""
        if not self.organization or not self.token:
            raise GitHubConfigurationError(
                "GitHub saving is not configured; set GITHUB_ORG and GITHUB_TOKEN on the backend."
            )
        if not _SAFE_IDENTIFIER.fullmatch(self.organization):
            raise GitHubConfigurationError(
                "GITHUB_ORG must be a valid GitHub organization name."
            )
        if not _SAFE_IDENTIFIER.fullmatch(euc_name) or euc_name in {".", ".."}:
            raise GitHubSaveError("EUC name is not valid for a GitHub repository.")
        root = Path(directory).resolve()
        if not root.is_dir() or not (root / "Dockerfile").is_file():
            raise GitHubSaveError("Generated EUC artifact directory is invalid.")
        tree_entries = self._tree_entries(root)

        repository = f"{self.organization}/{euc_name}"
        repository_url = f"https://github.com/{repository}"
        repo_path = f"/repos/{quote(self.organization, safe='')}/{quote(euc_name, safe='')}"
        repo_data = self._repository(repo_path, euc_name)
        branch = repo_data.get("default_branch") or "main"
        reference_path = f"{repo_path}/git/ref/heads/{quote(branch, safe='')}"
        current_reference = self._request("GET", reference_path, expected=(200, 404))
        first_save = current_reference is None

        parent_sha: str | None = None
        if current_reference is not None:
            parent_sha = current_reference["object"]["sha"]
            commit_data = self._request(
                "GET",
                f"{repo_path}/git/commits/{quote(parent_sha, safe='')}",
                expected=(200,),
            )
            existing_tree = self._request(
                "GET",
                f"{repo_path}/git/trees/{quote(commit_data['tree']['sha'], safe='')}?recursive=1",
                expected=(200,),
            )
            existing_paths = {
                entry.get("path")
                for entry in existing_tree.get("tree", [])
                if isinstance(entry, dict)
            }
            first_save = not {
                "src/main.py",
                "Dockerfile",
            }.issubset(existing_paths)

        tree = self._request(
            "POST",
            f"{repo_path}/git/trees",
            {"tree": tree_entries},
            expected=(201,),
        )
        commit_payload: dict[str, object] = {
            "message": (
                f"Create EUC {euc_name}" if first_save else f"Update EUC {euc_name}"
            ),
            "tree": tree["sha"],
            "parents": [parent_sha] if parent_sha else [],
        }
        commit = self._request(
            "POST",
            f"{repo_path}/git/commits",
            commit_payload,
            expected=(201,),
        )
        commit_sha = commit["sha"]

        if first_save:
            self._request(
                "POST",
                f"{repo_path}/git/refs",
                {"ref": f"refs/heads/{branch}", "sha": commit_sha},
                expected=(201,),
            )
        else:
            self._request(
                "PATCH",
                f"{repo_path}/git/refs/heads/{quote(branch, safe='')}",
                {"sha": commit_sha, "force": False},
                expected=(200,),
            )

        return {
            "euc_name": euc_name,
            "github_repo": repository,
            "github_url": repository_url,
            "github_commit_sha": commit_sha,
        }

    def _repository(self, path: str, euc_name: str) -> dict[str, object]:
        response = self._request("GET", path, expected=(200, 404))
        if response is not None:
            return response
        created = self._request(
            "POST",
            f"/orgs/{quote(self.organization or '', safe='')}/repos",
            {"name": euc_name, "private": True, "auto_init": False},
            expected=(201, 422),
        )
        if created is not None:
            return created
        # A concurrent save may have created the repository after the first GET.
        return self._request("GET", path, expected=(200,))

    def _tree_entries(self, root: Path) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            resolved = path.resolve()
            try:
                resolved.relative_to(root)
            except ValueError as error:
                raise GitHubSaveError(
                    "Generated artifact contains a file outside its directory."
                ) from error
            relative = path.relative_to(root).as_posix()
            pure = PurePosixPath(relative)
            if (
                pure.is_absolute()
                or relative != pure.as_posix()
                or ".." in pure.parts
                or "\\" in relative
            ):
                raise GitHubSaveError("Generated artifact contains an unsafe file path.")
            if any(part == ".env" or part.startswith(".env.") for part in pure.parts):
                continue
            try:
                content = resolved.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                raise GitHubSaveError(
                    "Generated artifact contains an unreadable file."
                ) from error
            entries.append(
                {
                    "path": relative,
                    "mode": "100644",
                    "type": "blob",
                    "content": content,
                }
            )
        if not entries:
            raise GitHubSaveError("Generated EUC artifact contains no committable files.")
        return entries

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> dict[str, object] | None:
        request = Request(
            f"{_API_ROOT}{path}",
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            response = self._http_open(request, timeout=30)
            status = getattr(response, "status", 200)
            body = response.read()
        except HTTPError as error:
            status = error.code
            body = error.read()
        except (OSError, URLError) as error:
            raise GitHubSaveError(
                "Unable to connect to GitHub while saving the EUC."
            ) from error

        if status not in expected:
            raise GitHubSaveError(
                f"GitHub request failed with HTTP {status}; the EUC was not saved."
            )
        if status == 404:
            return None
        if status == 422 and not body:
            return None
        try:
            data = json.loads(body.decode("utf-8")) if body else {}
        except (UnicodeError, json.JSONDecodeError) as error:
            raise GitHubSaveError(
                "GitHub returned an invalid response; the EUC was not saved."
            ) from error
        if not isinstance(data, dict):
            raise GitHubSaveError(
                "GitHub returned an invalid response; the EUC was not saved."
            )
        return data

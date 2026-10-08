"""Tests for the optional GitHub artifact-save integration."""

import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.migration import GeneratedEUC, GeneratedFile
from app.services.github import (
    GitHubConfigurationError,
    GitHubSaveError,
    GitHubService,
)
from app.services.migration.generator import generate_euc
from app.services.migration.validator import validate_directory


class FakeResponse:
    def __init__(self, status: int, body: dict[str, object]) -> None:
        self.status = status
        self._body = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._body


class FakeGitHub:
    """Minimal GitHub REST behavior for repository and Git-data operations."""

    def __init__(self) -> None:
        self.created = False
        self.head_sha: str | None = None
        self.commit_sha = 0
        self.commits: list[dict[str, object]] = []
        self.requests: list[tuple[str, str, dict[str, object] | None]] = []
        self.expected_token = "test-token-never-return-this"

    def open(self, request, timeout: int) -> FakeResponse:
        assert timeout == 30
        assert request.get_header("Authorization") == f"Bearer {self.expected_token}"
        path = urlsplit(request.full_url).path
        method = request.get_method()
        payload = json.loads(request.data) if request.data else None
        self.requests.append((method, path, payload))

        if method == "GET" and path == "/repos/example-org/direct-demo":
            return FakeResponse(200 if self.created else 404, {
                "default_branch": "main" if self.created else None,
            })
        if method == "POST" and path == "/orgs/example-org/repos":
            assert payload == {
                "name": "direct-demo",
                "private": True,
                "auto_init": False,
            }
            self.created = True
            return FakeResponse(201, {"default_branch": None})
        if method == "GET" and path.endswith("/git/ref/heads/main"):
            if self.head_sha is None:
                return FakeResponse(404, {})
            return FakeResponse(
                200,
                {"object": {"sha": self.head_sha}},
            )
        if method == "GET" and "/git/commits/" in path:
            return FakeResponse(
                200,
                {"tree": {"sha": self.commits[-1]["tree"]}},
            )
        if method == "GET" and "/git/trees/" in path:
            previous_tree = self.commits[0]["tree_payload"]["tree"]
            return FakeResponse(
                200,
                {"tree": [{"path": entry["path"]} for entry in previous_tree]},
            )
        if method == "POST" and path.endswith("/git/trees"):
            self.commits.append({"tree_payload": payload})
            return FakeResponse(201, {"sha": f"tree-{len(self.commits)}"})
        if method == "POST" and path.endswith("/git/commits"):
            self.commit_sha += 1
            self.commits[-1].update(payload or {})
            self.commits[-1]["sha"] = f"commit-{self.commit_sha}"
            return FakeResponse(201, {"sha": f"commit-{self.commit_sha}"})
        if method == "POST" and path.endswith("/git/refs"):
            self.head_sha = str(payload["sha"])
            return FakeResponse(201, {})
        if method == "PATCH" and path.endswith("/git/refs/heads/main"):
            self.head_sha = str(payload["sha"])
            return FakeResponse(200, {})
        raise AssertionError(f"Unexpected GitHub request: {method} {path}")


def _artifact(directory: Path) -> Path:
    files = [
        GeneratedFile(
            path="src/main.py",
            content="def run(input_data, context):\n    return input_data\n",
        ),
        GeneratedFile(path="src/logic.py", content="def helper():\n    return 1\n"),
        GeneratedFile(path="src/runner.py", content="print('runner')\n"),
        GeneratedFile(path="tests/test_logic.py", content="def test_ok():\n    assert True\n"),
        GeneratedFile(path="config/config.yaml", content="secret_references: {}\n"),
        GeneratedFile(path="requirements.txt", content="# none\n"),
        GeneratedFile(path="README.md", content="# direct-demo\n"),
        GeneratedFile(path="Dockerfile", content="FROM python:3.12-slim\n"),
    ]
    artifact = directory / "direct-demo"
    generate_euc(
        GeneratedEUC(
            name="direct-demo",
            files=files,
            warnings=["Test artifact"],
            unsupported_features=[],
        ),
        artifact,
    )
    assert validate_directory(artifact).valid
    return artifact


def test_github_configuration_is_optional_until_save_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_ORG", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    service = GitHubService(organization=None, token=None)

    with pytest.raises(GitHubConfigurationError, match="GITHUB_ORG and GITHUB_TOKEN"):
        service.save("direct-demo", Path("."))


def test_repository_created_and_first_save_creates_complete_commit(
    tmp_path: Path,
) -> None:
    artifact = _artifact(tmp_path)
    fake = FakeGitHub()
    result = GitHubService(
        "example-org",
        fake.expected_token,
        fake.open,
    ).save("direct-demo", artifact)

    tree_payload = fake.commits[0]["tree_payload"]
    paths = {entry["path"] for entry in tree_payload["tree"]}
    assert paths == {
        "src/main.py",
        "src/logic.py",
        "src/runner.py",
        "tests/test_logic.py",
        "config/config.yaml",
        "requirements.txt",
        "README.md",
        "Dockerfile",
    }
    assert fake.commits[0]["message"] == "Create EUC direct-demo"
    assert fake.commits[0]["parents"] == []
    assert result == {
        "euc_name": "direct-demo",
        "github_repo": "example-org/direct-demo",
        "github_url": "https://github.com/example-org/direct-demo",
        "github_commit_sha": "commit-1",
    }


def test_existing_repository_reused_and_second_save_commits_update(
    tmp_path: Path,
) -> None:
    artifact = _artifact(tmp_path)
    fake = FakeGitHub()
    service = GitHubService("example-org", fake.expected_token, fake.open)

    first = service.save("direct-demo", artifact)
    second = service.save("direct-demo", artifact)

    assert first["github_commit_sha"] == "commit-1"
    assert second["github_commit_sha"] == "commit-2"
    assert [item["message"] for item in fake.commits] == [
        "Create EUC direct-demo",
        "Update EUC direct-demo",
    ]
    assert sum(
        method == "POST" and path == "/orgs/example-org/repos"
        for method, path, _ in fake.requests
    ) == 1


def test_repository_name_is_derived_from_euc_name(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path)
    fake = FakeGitHub()

    result = GitHubService("example-org", fake.expected_token, fake.open).save(
        "direct-demo", artifact
    )

    assert result["github_repo"] == "example-org/direct-demo"
    assert all("client-org" not in path for _, path, _ in fake.requests)


def test_unsafe_euc_name_is_rejected(tmp_path: Path) -> None:
    service = GitHubService("example-org", "token", lambda *_args, **_kwargs: None)
    artifact = _artifact(tmp_path)
    with pytest.raises(GitHubSaveError, match="EUC name"):
        service.save("../other", artifact)


def test_unsafe_symlinked_artifact_path_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = GitHubService("example-org", "token", lambda *_args, **_kwargs: None)
    artifact = _artifact(tmp_path)
    outside = tmp_path / "outside.txt"

    class EscapingFile:
        def is_file(self) -> bool:
            return True

        def resolve(self) -> Path:
            return outside

    monkeypatch.setattr(Path, "rglob", lambda self, pattern: [EscapingFile()])
    with pytest.raises(GitHubSaveError, match="outside its directory"):
        service._tree_entries(artifact)


def test_env_files_are_never_committed(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path)
    (artifact / ".env").write_text("TOKEN=private", encoding="utf-8")
    service = GitHubService("example-org", "token", lambda *_args, **_kwargs: None)

    entries = service._tree_entries(artifact)

    assert ".env" not in {entry["path"] for entry in entries}


def test_github_failure_is_controlled_without_echoing_token(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path)

    def failing_open(*_args, **_kwargs):
        return FakeResponse(500, {"message": "backend error"})

    token = "secret-token-value"
    with pytest.raises(GitHubSaveError) as error:
        GitHubService("example-org", token, failing_open).save(
            "direct-demo", artifact
        )
    assert token not in str(error.value)


def test_save_endpoint_requires_backend_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _artifact(tmp_path)
    monkeypatch.setenv("EUC_OUTPUT_ROOT", str(tmp_path))
    monkeypatch.delenv("GITHUB_ORG", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    response = TestClient(app).post("/api/eucs/direct-demo/github")

    assert response.status_code == 503
    assert "GITHUB_ORG and GITHUB_TOKEN" in response.json()["detail"]
    assert "secret-token-value" not in response.text


def test_save_endpoint_uses_configured_org_and_never_returns_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _artifact(tmp_path)
    monkeypatch.setenv("EUC_OUTPUT_ROOT", str(tmp_path))
    monkeypatch.setenv("GITHUB_ORG", "configured-org")
    monkeypatch.setenv("GITHUB_TOKEN", "backend-only-token")

    class FakeService:
        def __init__(self) -> None:
            pass

        def save(self, name: str, directory: Path) -> dict[str, str]:
            assert name == "direct-demo"
            assert directory == tmp_path / "direct-demo"
            return {
                "euc_name": name,
                "github_repo": "configured-org/direct-demo",
                "github_url": "https://github.com/configured-org/direct-demo",
                "github_commit_sha": "commit-abc",
            }

    monkeypatch.setattr("app.api.eucs.GitHubService", FakeService)
    response = TestClient(app).post(
        "/api/eucs/direct-demo/github",
        json={"organization": "client-org", "repository": "client-repo"},
    )

    assert response.status_code == 200
    assert response.json()["github_repo"] == "configured-org/direct-demo"
    assert "backend-only-token" not in response.text
    assert "client-org" not in response.text
    assert "client-repo" not in response.text
    details = TestClient(app).get("/api/eucs/direct-demo")
    assert details.status_code == 200
    assert details.json()["github_repo"] == "configured-org/direct-demo"
    assert details.json()["github_commit_sha"] == "commit-abc"


def test_repository_creation_failure_is_controlled(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path)
    requests: list[tuple[str, str]] = []

    def failed_creation_open(request, timeout: int) -> FakeResponse:
        del timeout
        path = urlsplit(request.full_url).path
        method = request.get_method()
        requests.append((method, path))
        if method == "GET":
            return FakeResponse(404, {})
        return FakeResponse(500, {"message": "internal details"})

    with pytest.raises(GitHubSaveError, match="HTTP 500") as error:
        GitHubService("example-org", "secret-value", failed_creation_open).save(
            "direct-demo", artifact
        )
    assert requests[-1] == ("POST", "/orgs/example-org/repos")
    assert "internal details" not in str(error.value)
    assert "secret-value" not in str(error.value)


def test_commit_failure_is_controlled_and_not_reported_as_success(
    tmp_path: Path,
) -> None:
    artifact = _artifact(tmp_path)
    fake = FakeGitHub()
    original_open = fake.open

    def fail_commit(request, timeout: int) -> FakeResponse:
        if request.get_method() == "POST" and request.full_url.endswith("/git/commits"):
            return FakeResponse(500, {"message": "failure"})
        return original_open(request, timeout)

    with pytest.raises(GitHubSaveError, match="HTTP 500"):
        GitHubService("example-org", fake.expected_token, fail_commit).save(
            "direct-demo", artifact
        )


def test_save_endpoint_rejects_invalid_artifact_and_missing_euc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EUC_OUTPUT_ROOT", str(tmp_path))
    invalid_artifact = tmp_path / "invalid-euc"
    invalid_artifact.mkdir()
    (invalid_artifact / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")

    invalid = TestClient(app).post("/api/eucs/invalid-euc/github")
    missing = TestClient(app).post("/api/eucs/missing-euc/github")

    assert invalid.status_code == 422
    assert missing.status_code == 404

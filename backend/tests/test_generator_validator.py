"""Tests for EUC packaging and deterministic validation."""

from pathlib import Path

import pytest
from app.schemas.migration import GeneratedEUC, GeneratedFile
from app.services.migration.generator import generate
from app.services.migration.validator import validate


def _euc(*files: tuple[str, str]) -> GeneratedEUC:
    return GeneratedEUC(
        name="demo",
        files=[GeneratedFile(path=path, content=content) for path, content in files],
        warnings=[],
        unsupported_features=[],
    )


def test_generate_writes_nested_files_deterministically(tmp_path: Path) -> None:
    generated = _euc(("src/main.py", "print('ok')\n"), ("README.md", "# demo\n"))
    written = generate(generated, tmp_path)
    assert [path.relative_to(tmp_path).as_posix() for path in written] == ["src/main.py", "README.md"]
    assert (tmp_path / "src/main.py").read_text(encoding="utf-8") == "print('ok')\n"


@pytest.mark.parametrize("path", ["", "../escape.py", "/absolute.py", r"src\main.py", "src/../main.py"])
def test_generate_rejects_unsafe_paths_before_writing(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError):
        generate(_euc((path, "content")), tmp_path)
    assert not list(tmp_path.rglob("*"))


def test_generate_rejects_duplicate_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        generate(_euc(("README.md", "a"), ("README.md", "b")), tmp_path)


def test_generate_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "src"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this platform.")

    with pytest.raises(ValueError, match="escapes the destination"):
        generate(_euc(("src/main.py", "content")), tmp_path)
    assert not (outside / "main.py").exists()


def test_validate_accepts_safe_complete_euc() -> None:
    result = validate(
        _euc(
            ("src/main.py", "from .logic import run\n"),
            ("src/logic.py", "def run():\n    return 1\n"),
            ("tests/test_logic.py", "def test_run():\n    assert True\n"),
            ("config/config.yaml", "endpoint: ${ENDPOINT}\n"),
            ("requirements.txt", "requests\n"),
            ("README.md", "# demo\n"),
            ("Dockerfile", "FROM python:3.12-slim\n"),
        )
    )
    assert result.valid
    assert result.errors == []


def test_validate_reports_structure_syntax_maxx_and_secret_without_execution() -> None:
    result = validate(
        _euc(
            ("src/main.py", "def broken(:\n    pass\n"),
            ("src/logic.py", "import sglambdautils\npassword = 'not-a-secret'\n"),
        )
    )
    assert not result.valid
    assert any("Missing required file" in error for error in result.errors)
    assert any("syntax" in error for error in result.errors)
    assert any("MAXX" in error for error in result.errors)
    assert any("hardcoded secret" in error for error in result.errors)


def test_validate_rejects_get_lambda_secret_call() -> None:
    result = validate(
        _euc(
            ("src/main.py", "value = get_lambda_secret('client_id')\n"),
            ("tests/test_logic.py", "def test_value():\n    assert True\n"),
            ("config/config.yaml", "secret: ${CLIENT_ID}\n"),
            ("requirements.txt", ""),
            ("README.md", "# demo\n"),
            ("Dockerfile", "FROM python:3.12-slim\n"),
        )
    )

    assert not result.valid
    assert any("MAXX runtime dependency leakage" in error for error in result.errors)


def test_validate_allows_get_lambda_secret_text_without_a_call() -> None:
    result = validate(
        _euc(
            ("src/main.py", '# Migration note: get_lambda_secret is not used.\n'),
            ("tests/test_logic.py", "def test_value():\n    assert True\n"),
            ("config/config.yaml", "secret: ${CLIENT_ID}\n"),
            ("requirements.txt", "requests\n"),
            ("README.md", "Use the phrase get_lambda_secret in migration docs.\n"),
            ("Dockerfile", "FROM python:3.12-slim\n"),
        )
    )

    assert result.valid


def test_validate_allows_environment_and_configuration_references() -> None:
    result = validate(
        _euc(
            ("src/main.py", "import os\nvalue = os.environ.get('CLIENT_ID')\n"),
            ("tests/test_logic.py", "def test_value():\n    assert True\n"),
            ("config/config.yaml", "client_id: ${CLIENT_ID}\n"),
            ("requirements.txt", "requests\n"),
            ("README.md", "# demo\n"),
            ("Dockerfile", "FROM python:3.12-slim\n"),
        )
    )

    assert result.valid


@pytest.mark.parametrize(
    "required_path",
    [
        "src/main.py",
        "config/config.yaml",
        "requirements.txt",
        "README.md",
        "Dockerfile",
    ],
)
@pytest.mark.parametrize("content", ["", " \n\t"])
def test_validate_rejects_empty_required_files(
    required_path: str, content: str
) -> None:
    files = {
        "src/main.py": "print('ok')\n",
        "tests/test_logic.py": "def test_ok():\n    assert True\n",
        "config/config.yaml": "endpoint: ${ENDPOINT}\n",
        "requirements.txt": "requests\n",
        "README.md": "# demo\n",
        "Dockerfile": "FROM python:3.12-slim\n",
    }
    files[required_path] = content

    result = validate(_euc(*files.items()))

    assert not result.valid
    assert f"Required file '{required_path}' is empty." in result.errors

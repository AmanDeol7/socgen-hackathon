"""Tests for the standardized EUC stdin/stdout runtime contract."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.migration.runtime import RUNNER_CONTENT


def _run_euc(tmp_path: Path, main_source: str, input_text: str) -> subprocess.CompletedProcess[str]:
    src = tmp_path / "src"
    src.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "main.py").write_text(main_source, encoding="utf-8")
    (src / "runner.py").write_text(RUNNER_CONTENT, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "src.runner"],
        cwd=tmp_path,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def test_runner_serializes_successful_result(tmp_path: Path) -> None:
    completed = _run_euc(
        tmp_path,
        "def run(input_data, context):\n    return {'success': True, 'value': input_data['value']}\n",
        '{"value": 42}',
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {"success": True, "value": 42}
    assert completed.stderr == ""


@pytest.mark.parametrize(
    ("input_text", "error"),
    [
        ("", "non-empty JSON object"),
        ("not json", "invalid JSON input"),
        ("[]", "JSON object"),
    ],
)
def test_runner_rejects_invalid_input(
    tmp_path: Path, input_text: str, error: str
) -> None:
    completed = _run_euc(
        tmp_path,
        "def run(input_data, context):\n    return input_data\n",
        input_text,
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert error in completed.stderr


def test_runner_reports_missing_business_input_without_success_output(
    tmp_path: Path,
) -> None:
    completed = _run_euc(
        tmp_path,
        (
            "def run(input_data, context):\n"
            "    if 'customer_id' not in input_data:\n"
            "        raise ValueError('customer_id is required')\n"
            "    return {'success': True}\n"
        ),
        "{}",
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert "customer_id is required" in completed.stderr


def test_runner_handles_unexpected_failure_without_leaking_secret(
    tmp_path: Path,
) -> None:
    completed = _run_euc(
        tmp_path,
        (
            "def run(input_data, context):\n"
            "    raise RuntimeError('client_secret=do-not-print')\n"
        ),
        "{}",
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert "unexpectedly" in completed.stderr
    assert "do-not-print" not in completed.stderr

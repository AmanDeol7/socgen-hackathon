"""Tests for deterministic MAXX EUC static analysis."""

import pytest

from app.services.migration.analyzer import analyze


def test_detects_normal_imports() -> None:
    result = analyze("import os\nimport requests\nfrom pathlib import Path\n")

    assert result.imports == ["os", "requests", "pathlib"]
    assert result.maxx_imports == []


def test_detects_maxx_imports_and_secret_usage() -> None:
    source = """
from sglambdautils.context import LambdaContext
from sglambdautils.lambda_secret.secret import get_lambda_secret

def run(json_input):
    client_id = get_lambda_secret("client_id")
    client_secret = get_lambda_secret("client_secret")
    return json_input
"""

    result = analyze(source)

    assert result.maxx_imports == [
        "sglambdautils.context",
        "sglambdautils.lambda_secret.secret",
    ]
    assert result.secret_usages == ["client_id", "client_secret"]


def test_detects_functions_arguments_and_line_ranges() -> None:
    source = """\
def first(value, /, optional=True, *args, keyword, **kwargs):
    return value

async def second():
    return None
"""

    result = analyze(source)

    assert [(function.name, function.arguments) for function in result.functions] == [
        (
            "first",
            ["value", "optional", "args", "keyword", "kwargs"],
        ),
        ("second", []),
    ]
    assert (result.functions[0].line_start, result.functions[0].line_end) == (1, 2)
    assert (result.functions[1].line_start, result.functions[1].line_end) == (4, 5)


def test_detects_run_entrypoint() -> None:
    result = analyze("def run(json_input):\n    return json_input\n")

    assert result.entrypoint == "run"
    assert result.functions[0].name == "run"


def test_detects_external_urls_in_strings() -> None:
    source = """
API_URL = "https://example.internal/api"
message = "See http://example.com/status"
"""

    result = analyze(source)

    assert result.external_urls == [
        "https://example.internal/api",
        "http://example.com/status",
    ]


def test_reports_dynamic_secret_and_suspicious_calls() -> None:
    result = analyze(
        "secret_name = input()\n"
        "value = get_lambda_secret(secret_name)\n"
        "result = eval('1 + 1')\n"
    )

    assert any("dynamically determined secret name" in warning for warning in result.warnings)
    assert any("eval()" in warning for warning in result.warnings)


def test_malformed_python_raises_useful_error() -> None:
    with pytest.raises(ValueError, match=r"Unable to parse Python source at line 1"):
        analyze("def broken(:\n    pass\n")


def test_detects_multiple_functions() -> None:
    result = analyze(
        "def first():\n"
        "    pass\n"
        "\n"
        "def second(value):\n"
        "    return value\n"
    )

    assert [function.name for function in result.functions] == ["first", "second"]


def test_source_without_run_or_maxx_dependencies() -> None:
    result = analyze("def calculate(value):\n    return value + 1\n")

    assert result.entrypoint is None
    assert result.maxx_imports == []
    assert result.secret_usages == []
    assert result.warnings == []

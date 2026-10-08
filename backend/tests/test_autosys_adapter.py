"""Tests for the standard-library local AutoSys adapter."""

import io
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request

import pytest

_ADAPTER_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "autosys" / "run_euc.py"
)
_ADAPTER_SPEC = spec_from_file_location("autosys_run_euc", _ADAPTER_PATH)
assert _ADAPTER_SPEC is not None and _ADAPTER_SPEC.loader is not None
run_euc = module_from_spec(_ADAPTER_SPEC)
_ADAPTER_SPEC.loader.exec_module(run_euc)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _response(
    *,
    status: str = "COMPLETED",
    exit_code: int | None = 0,
    stdout: str = '{"message": "Hello, Aman"}',
    stderr: str = "",
) -> FakeResponse:
    result = {
        "euc_name": "customer-greeting",
        "execution_id": "exec-test",
        "status": status,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
    }
    return FakeResponse(json.dumps(result).encode("utf-8"))


def test_success_submits_euc_and_input_and_returns_zero(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: int):
        captured["request"] = request
        captured["timeout"] = timeout
        return _response()

    monkeypatch.setattr(run_euc, "urlopen", fake_urlopen)
    monkeypatch.setenv("EUC_PLATFORM_URL", "http://localhost:8000/")

    exit_code = run_euc.main(
        ["customer-greeting", "--input-json", '{"name":"Aman"}']
    )

    request = captured["request"]
    assert isinstance(request, Request)
    assert request.full_url == "http://localhost:8000/api/executions"
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == {
        "euc_name": "customer-greeting",
        "input": {"name": "Aman"},
    }
    assert captured["timeout"] == 120
    assert exit_code == 0
    assert "Execution ID: exec-test" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("status", "exit_code"),
    [("FAILED", 1), ("TIMED_OUT", None), ("COMPLETED", 2)],
)
def test_failed_execution_returns_nonzero(status, exit_code, monkeypatch) -> None:
    monkeypatch.setattr(
        run_euc,
        "urlopen",
        lambda *_args, **_kwargs: _response(
            status=status,
            exit_code=exit_code,
            stderr="EUC execution failed",
        ),
    )

    assert (
        run_euc.main(
            ["customer-greeting", "--input-json", '{"name":"Aman"}'],
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
        == 1
    )


@pytest.mark.parametrize("input_json", ["{invalid", "[]", '"text"', "null"])
def test_malformed_or_non_object_input_returns_nonzero(input_json, monkeypatch) -> None:
    def unexpected_request(*_args, **_kwargs):
        pytest.fail("Invalid input must not make an API request.")

    monkeypatch.setattr(run_euc, "urlopen", unexpected_request)

    assert (
        run_euc.main(
            ["customer-greeting", "--input-json", input_json],
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
        == 2
    )


def test_api_unavailable_returns_nonzero(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        run_euc,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("offline")),
    )

    assert (
        run_euc.main(
            ["customer-greeting", "--input-json", "{}"]
        )
        == 1
    )
    assert "Unable to reach EUC Platform API" in capsys.readouterr().err


def test_sensitive_output_is_suppressed_and_no_auth_header_is_sent(
    monkeypatch,
    capsys,
) -> None:
    captured_request: list[Request] = []

    def fake_urlopen(request: Request, timeout: int):
        captured_request.append(request)
        return _response(
            stdout="safe result\napi_key=private-value",
            stderr="token=private-value",
        )

    monkeypatch.setattr(run_euc, "urlopen", fake_urlopen)

    assert (
        run_euc.main(
            ["customer-greeting", "--input-json", '{"api_key":"private-value"}']
        )
        == 0
    )
    printed = capsys.readouterr()
    assert "private-value" not in printed.out + printed.err
    assert captured_request[0].get_header("Authorization") is None

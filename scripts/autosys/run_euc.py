"""Submit one EUC execution to the local platform API for a scheduler."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import TextIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_DEFAULT_PLATFORM_URL = "http://127.0.0.1:8000"
_SENSITIVE_LINE = re.compile(
    r"(?i)(secret|password|token|api[\s_-]?key|authorization|credential)"
)


def main(
    argv: list[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Parse CLI arguments, submit an execution request, and report its result."""
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("euc_name", help="registered EUC name to execute")
    parser.add_argument(
        "--input-json",
        required=True,
        help="JSON object passed as the EUC input",
    )
    args = parser.parse_args(argv)

    try:
        euc_input = json.loads(args.input_json)
    except json.JSONDecodeError as error:
        print(f"Invalid --input-json: {error.msg}.", file=errors)
        return 2
    if not isinstance(euc_input, dict):
        print("Invalid --input-json: expected a JSON object.", file=errors)
        return 2

    payload = json.dumps(
        {"euc_name": args.euc_name, "input": euc_input}
    ).encode("utf-8")
    base_url = os.environ.get("EUC_PLATFORM_URL", _DEFAULT_PLATFORM_URL).rstrip("/")
    request = Request(
        f"{base_url}/api/executions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        _print_http_error(error, errors)
        return 1
    except (URLError, TimeoutError, OSError):
        print("Unable to reach EUC Platform API.", file=errors)
        return 1
    except (UnicodeDecodeError, json.JSONDecodeError):
        print("EUC Platform returned an invalid JSON response.", file=errors)
        return 1
    except ValueError:
        print("EUC_PLATFORM_URL is invalid.", file=errors)
        return 1

    if not isinstance(result, dict):
        print("EUC Platform returned an unexpected execution response.", file=errors)
        return 1
    required_fields = ("execution_id", "status", "exit_code", "stdout", "stderr")
    if any(field not in result for field in required_fields):
        print("EUC Platform returned an incomplete execution response.", file=errors)
        return 1

    print(f"EUC: {_sanitize(str(result.get('euc_name', args.euc_name)))}", file=output)
    print(f"Execution ID: {_sanitize(str(result['execution_id']))}", file=output)
    print(f"Status: {_sanitize(str(result['status']))}", file=output)
    print(f"Exit code: {_sanitize(str(result['exit_code']))}", file=output)
    _print_result("Result", result["stdout"], output)
    _print_result("Error", result["stderr"], output)

    return 0 if result["status"] == "COMPLETED" and result["exit_code"] == 0 else 1


def _print_http_error(error: HTTPError, output: TextIO) -> None:
    """Print a controlled API failure without echoing request credentials."""
    try:
        payload = json.loads(error.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError):
        payload = None
    detail = payload.get("detail") if isinstance(payload, dict) else None
    message = (
        _sanitize(str(detail))
        if detail is not None
        else "The execution request was rejected."
    )
    print(f"EUC Platform API returned HTTP {error.code}: {message}", file=output)


def _print_result(label: str, value: object, output: TextIO) -> None:
    if not isinstance(value, str) or not value:
        return
    safe_value = _sanitize(value)
    if safe_value:
        print(f"{label}:\n{safe_value}", file=output)


def _sanitize(value: str) -> str:
    """Suppress output lines likely to contain sensitive runtime values."""
    return "\n".join(
        "Execution output suppressed." if _SENSITIVE_LINE.search(line) else line
        for line in value.splitlines()
    )


if __name__ == "__main__":
    raise SystemExit(main())

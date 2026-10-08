"""Deterministic execution-contract materialisation for standardized EUCs."""

from __future__ import annotations

from app.schemas.migration import GeneratedEUC, GeneratedFile

RUNNER_CONTENT = '''"""Deterministic stdin/stdout runtime adapter for this standardized EUC."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from src.main import run


def main() -> int:
    """Read one JSON object, invoke the EUC, and emit one JSON result."""
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            raise ValueError("input must be a non-empty JSON object")
        input_data = json.loads(raw_input)
        if not isinstance(input_data, dict):
            raise ValueError("input must be a JSON object")
        result = run(input_data, SimpleNamespace())
        if not isinstance(result, dict):
            raise TypeError("EUC run() must return a JSON object")
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\\n")
        return 0
    except json.JSONDecodeError as error:
        return _fail(f"invalid JSON input: {error.msg}")
    except ValueError as error:
        return _fail(str(error))
    except Exception:
        return _fail("EUC execution failed unexpectedly")


def _fail(message: str) -> int:
    """Write a controlled failure without exposing runtime values."""
    lowered = message.lower()
    if any(secret_word in lowered for secret_word in ("secret", "token", "password", "api key")):
        message = "EUC execution failed due to protected configuration."
    print(f"Execution failed: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


def ensure_execution_contract(generated_euc: GeneratedEUC) -> GeneratedEUC:
    """Add the fixed runner and enforce its Docker entrypoint."""
    files = list(generated_euc.files)
    paths = {generated_file.path for generated_file in files}
    if "src/runner.py" not in paths:
        files.append(GeneratedFile(path="src/runner.py", content=RUNNER_CONTENT))

    for index, generated_file in enumerate(files):
        if generated_file.path == "Dockerfile":
            files[index] = GeneratedFile(
                path=generated_file.path,
                content=_with_runner_entrypoint(generated_file.content),
            )
            break

    return generated_euc.model_copy(update={"files": files})


def _with_runner_entrypoint(content: str) -> str:
    """Remove executable Docker commands and set the standard runner command."""
    lines = [
        line
        for line in content.splitlines()
        if not line.strip().startswith(("ENTRYPOINT", "CMD"))
    ]
    lines.append('ENTRYPOINT ["python", "-m", "src.runner"]')
    return "\n".join(lines) + "\n"

# Standard EUC Specification

This specification is a shared team contract for standardized EUCs. It must not
be changed without team agreement.

## Required structure

```text
euc-name/
├── src/
│   ├── main.py
│   ├── runner.py
│   └── logic.py
├── tests/
│   └── test_logic.py
├── config/
│   └── config.yaml
├── requirements.txt
├── README.md
└── Dockerfile
```

## Rules

1. `src/main.py` exposes `run(input_data: dict, context) -> dict`.
2. `src/runner.py` is the deterministic container entrypoint and must not
   contain business logic.
3. Business logic should be separated where practical.
4. Tests belong under `tests/`.
5. Runtime configuration belongs under `config/` or environment variables.
6. Secrets must never be stored in source code.
7. Only secret references may be stored in configuration.
8. MAXX-specific runtime dependencies must not remain in migrated code.
9. External API behavior should be preserved during migration.
10. Business logic should be preserved.
11. Migrated code should be testable.
12. `Dockerfile` is part of the standard because the eventual execution
    environment will use containers.
13. Every generated EUC must be structurally valid before it can proceed to
    later certification.

## Execution contract

The container reads one JSON object from stdin:

```bash
echo '{"customer_id":"12345"}' | docker run --rm -i euc-image
```

The Dockerfile entrypoint runs `python -m src.runner`. The runner passes the
object and a minimal context to `src.main.run()` and writes the returned JSON
object to stdout.

- Success: one JSON object on stdout and exit code `0`.
- Failure: no successful result on stdout, a controlled error on stderr, and a
  non-zero exit code.
- Empty input, malformed JSON, and non-object JSON are failures.
- Errors must not contain API keys, tokens, passwords, or secret values.
- The runner does not execute shell commands or select modules/functions from
  input.

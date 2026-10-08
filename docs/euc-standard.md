# Standard EUC Specification

This specification is a shared team contract for standardized EUCs. It must not
be changed without team agreement.

## Required structure

```text
euc-name/
├── src/
│   ├── main.py
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

1. `src/main.py` is the standardized entrypoint.
2. Business logic should be separated where practical.
3. Tests belong under `tests/`.
4. Runtime configuration belongs under `config/` or environment variables.
5. Secrets must never be stored in source code.
6. Only secret references may be stored in configuration.
7. MAXX-specific runtime dependencies must not remain in migrated code.
8. External API behavior should be preserved during migration.
9. Business logic should be preserved.
10. Migrated code should be testable.
11. `Dockerfile` is part of the standard because the eventual execution
    environment will use containers.
12. Every generated EUC must be structurally valid before it can proceed to
    later certification.

# EUC Platform Agent Instructions

## Repository purpose

The EUC Platform is an MVP for migrating MAXX Python EUCs into standardized
Python applications. Development is sequential and performed by AI coding
agents on a single laptop. Agents are assigned narrowly scoped
responsibilities.

## Shared contracts

The following files are shared contracts and must not be changed without
explicit architectural approval:

- `backend/app/schemas/migration.py`
- `docs/euc-standard.md`

## Project principles

1. Keep the architecture simple.
2. Do not introduce microservices.
3. Do not add LangChain.
4. Do not add agent frameworks.
5. Do not add Redis.
6. Do not add Celery.
7. Do not add Kafka.
8. Do not add Kubernetes.
9. Do not add PostgreSQL during the migration-framework milestone.
10. Do not add cloud infrastructure during the migration-framework milestone.
11. Do not add AutoSys integration yet.
12. Do not add enterprise logging yet.
13. Do not add authentication yet.
14. Do not hardcode secrets.
15. Do not invent external APIs, credentials, or business behavior.
16. Prefer deterministic logic over LLM logic whenever possible.
17. LLMs may assist with semantic code transformation but must not define
    metadata or shared contracts.
18. Use Python type hints.
19. Use Pydantic models for service and API contracts.
20. Write tests for implemented functionality.
21. Run `pytest` and `ruff` before declaring work complete.
22. Do not modify unrelated modules.
23. Do not silently change existing behavior.
24. Do not rewrite working code unnecessarily.

## Current migration pipeline

```text
MAXX EUC
→ deterministic AST analysis
→ LLM-assisted transformation
→ standardized EUC
→ deterministic validation
```

The deterministic stages should remain the source of truth for structural
analysis and validation. LLM assistance is limited to semantic transformation.

## Standardized EUC structure

Every standardized EUC follows the structure defined in
`docs/euc-standard.md`:

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

The standard requires:

- `src/main.py` as the standardized entrypoint.
- Business logic separated where practical.
- Tests under `tests/`.
- Runtime configuration under `config/` or environment variables.
- No secrets in source code; configuration may contain only secret references.
- No MAXX-specific runtime dependencies in migrated code.
- Preservation of external API behavior and business logic.
- Testable migrated code.
- A `Dockerfile` as part of the eventual container-based execution standard.
- Structural validation before an EUC proceeds to later certification.

## Working rules for every task

1. Read the existing code first.
2. Understand the current architecture.
3. Make the smallest reasonable change.
4. Stay within the assigned responsibility.
5. Run relevant tests.
6. Report files changed.
7. Report tests run.
8. Report remaining issues.

Do not implement application functionality as part of this instruction file
change. Keep changes narrowly scoped and avoid unrelated modifications.
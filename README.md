# EUC Platform

A cloud-ready platform for migrating MAXX EUCs into standardized Python
applications.

## Current milestone

Migration framework.

```text
MAXX EUC
→ AST analysis
→ LLM-assisted transformation
→ standardized EUC
→ validation
```

The current scope excludes cloud deployment, AutoSys, PostgreSQL, enterprise
logging, authentication, and production infrastructure.

## Local setup

1. Create a Python 3.12 virtual environment.
2. From the `backend` directory, install the dependencies:

   ```powershell
   pip install -r requirements.txt -r requirements-dev.txt
   ```

3. From the `backend` directory, run:

   ```powershell
   uvicorn app.main:app --reload
   ```

4. Verify that `GET /health` returns `{"status": "ok"}`.

`backend/app/schemas/migration.py` and `docs/euc-standard.md` are shared
contracts and should not be changed without team agreement.

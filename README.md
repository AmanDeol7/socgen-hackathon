# EUC Platform

A cloud-ready platform for migrating MAXX EUCs into standardized Python
applications.

## Current milestone

Migration framework.

```

The LLM is limited to semantic business-code transformation. The platform
deterministically assembles the standard runner, Dockerfile, configuration,
requirements, README, and directory structure from migration metadata and
analysis before validating the final EUC package.text
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

## LLM Configuration

The migration endpoint uses OpenRouter only when `OPENROUTER_API_KEY` is set.
Without a key, requests fail with a controlled transformation error and no
network request is attempted.

Configure the backend process with:

```text
OPENROUTER_API_KEY=your-key
LLM_MODEL=openrouter/free
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

`LLM_MODEL` and `OPENROUTER_BASE_URL` are optional and default to the values
shown above. Keep the API key in the environment or a local `.env` file; do
not commit credentials. The provider sends the transformer prompt to
`/chat/completions` synchronously and sanitizes upstream failures before they
reach the API response.

## Local EUC execution

The migration endpoint only creates and validates standardized EUCs. It does
not execute them. An already-generated EUC can be run synchronously through
Docker with:

```http
POST /api/executions
Content-Type: application/json
```

```json
{
  "euc_name": "customer-reconciliation",
  "input": {
    "records": [1, 2, 3]
  }
}
```

The response contains an `execution_id`, lifecycle `status`, timezone-aware
timestamps, `duration_ms`, `euc_name`, `exit_code`, `stdout`, and `stderr`.
Statuses are `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, and `TIMED_OUT`.
The service derives the Docker image name from registry metadata and invokes
the standardized `python -m src.runner` container entrypoint.
Docker must be installed and running locally. Set `EUC_OUTPUT_ROOT` to the
local generated-EUC directory when needed and optionally set
`EUC_EXECUTION_TIMEOUT_SECONDS` (default: 30 seconds).

Execution records can be retrieved with:

```http
GET /api/executions/{execution_id}
GET /api/executions
```

Lifecycle records are stored only in process-local memory. Execution history
disappears when the backend restarts; no persistent execution database is used.

AutoSys is a future external scheduler and is not part of this local execution
service.

### Local EUC registry

The local execution service uses an in-memory registry that maps a logical EUC
name to validated execution metadata: Docker image, version, and generated
artifact path. Successful migrations register their generated artifact after
validation and generation. Existing generated EUCs are discovered on first
execution so the current local workflow remains compatible. Callers provide
only the logical EUC name; future schedulers such as AutoSys will use that
name rather than Docker or filesystem details.

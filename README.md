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
   uvicorn app.main:app --reload --reload-dir app
   ```

   Limit reload watching to application code so generated EUC files in
   `backend/output` do not trigger a backend reload and clear process-local
   registry metadata such as owners and certification state.

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

The migration endpoint creates and validates standardized EUCs, writes their
files, and builds a local Docker image before registering them as executable.
Execution runs that already-built image synchronously through Docker with:

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
the standardized `python -m src.runner` container entrypoint. Docker must be
installed and running locally for migration image builds and execution. Set `EUC_OUTPUT_ROOT` to the
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

The local execution service loads its registry into memory from
`<EUC_OUTPUT_ROOT>/.euc-registry.json` (default: `output/.euc-registry.json`).
It persists owners, certification state, and GitHub repository metadata alongside
the Docker image, version, and generated artifact path, so those details remain
available after a backend restart. Successful migrations register an artifact
only after validation and image building succeed. Existing generated EUCs
without registry metadata are discovered for compatibility, but owner data that
was previously held only in memory cannot be recovered automatically.
Callers provide only the logical EUC name, not Docker or filesystem details.

### Edit existing EUCs

Existing EUCs can be edited with `PUT /api/eucs/{name}`. The request contains
a `files` array of `{ "path": ..., "content": ... }` entries and accepts only
`src/main.py`, `src/logic.py`, or business Python tests under `tests/`.
Validation and a Docker image rebuild happen in a staging directory before the
artifact is replaced. A successful meaningful edit to a certified EUC clears
its approval and returns it to `PENDING_APPROVAL`.

### Save EUCs to GitHub

GitHub saving is optional and separate from EUC creation and migration.
Configure the backend process with `GITHUB_ORG` and `GITHUB_TOKEN`; keep the
token backend-only and do not commit it. Use **Save to GitHub** on an EUC to
create or reuse `<GITHUB_ORG>/<euc-name>` and commit the complete validated
standardized artifact. The API returns the repository URL and commit SHA.
Subsequent saves create ordinary Git commits; no additional version store is
used.

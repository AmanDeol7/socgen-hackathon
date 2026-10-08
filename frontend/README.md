# EUC Migration Platform Frontend

The frontend is a small React and TypeScript application for submitting MAXX
Python EUCs to the EUC Platform migration API and displaying the migration
result.

## Prerequisites

- Node.js and npm
- The backend running locally on `http://localhost:8000`

The frontend calls:

```text
POST http://localhost:8000/api/migrations
```

The backend must allow the Vite development origin
`http://localhost:5173`.

## Install dependencies

From this directory:

```powershell
npm install
```

## Run the development server

```powershell
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in a browser.

Start the backend separately from the repository's `backend` directory:

```powershell
uvicorn app.main:app --reload
```

## Build for production

```powershell
npm run build
```

To preview the production build locally:

```powershell
npm run preview
```

## User workflow

1. Enter the required EUC metadata:
   - name
   - Python version
   - owner team
   - support team
2. Optionally enter a description, schedule, or SharePoint URL.
3. Paste the MAXX Python source into the source area.
4. Select **Migrate EUC**.
5. Review the migration status, validation result, warnings, unsupported
   features, and generated file paths.

The submit button remains disabled until the required fields and source code
are present. While a request is running, duplicate submissions are prevented
and a loading status is shown.

## Project structure

```text
frontend/
├── src/
│   ├── api.ts         # Typed API client and migration contracts
│   ├── App.tsx        # Migration form and result display
│   ├── main.tsx       # React entry point
│   └── styles.css     # Responsive application styling
├── index.html
├── package.json
├── tsconfig.json
└── vite.config.ts
```

The TypeScript interfaces in `src/api.ts` mirror the backend migration
contracts. Fetching is centralized in `migrateEuc()` rather than being
performed directly from React components.

## Error handling

The UI reports:

- backend connection failures
- non-success HTTP responses
- invalid JSON responses
- malformed migration results
- validation failures returned by the backend

Raw stack traces, provider errors, and secret values are not displayed.

## Current limitations

- The API URL is currently fixed to `http://localhost:8000/api/migrations`.
- No frontend test framework is configured; validation currently uses the
  TypeScript/Vite production build and manual browser verification.
- The default backend provider is intentionally unconfigured, so a normal
  local request may return a controlled migration failure until a provider is
  injected for development or testing.

"""FastAPI application entrypoint for the EUC Platform."""

from fastapi import FastAPI

from app.api.migration import router as migration_router

app = FastAPI(title="MAXX EUC Migration Platform", version="0.1.0")
app.include_router(migration_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Return the service health status."""
    return {"status": "ok"}

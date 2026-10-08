"""FastAPI application entrypoint for the EUC Platform."""

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.execution import router as execution_router
from app.api.migration import router as migration_router

load_dotenv()

app = FastAPI(title="MAXX EUC Migration Platform", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(migration_router)
app.include_router(execution_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Return the service health status."""
    return {"status": "ok"}

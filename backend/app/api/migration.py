"""Thin FastAPI endpoint for synchronous EUC migrations."""

import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends

from app.schemas.migration import MigrationInput, MigrationResult
from app.services.migration.orchestrator import (
    MigrationOrchestrator,
    UnconfiguredLLMProvider,
)

router = APIRouter()


def get_orchestrator() -> MigrationOrchestrator:
    """Build the local-development orchestrator dependency."""
    output_root = Path(os.getenv("EUC_OUTPUT_ROOT", "output"))
    return MigrationOrchestrator(UnconfiguredLLMProvider(), output_root)


@router.post("/api/migrations", response_model=MigrationResult)
def create_migration(
    migration_input: MigrationInput,
    orchestrator: Annotated[MigrationOrchestrator, Depends(get_orchestrator)],
) -> MigrationResult:
    """Run one migration synchronously."""
    return orchestrator.migrate(migration_input)

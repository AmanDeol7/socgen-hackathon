"""Thin FastAPI endpoint for synchronous EUC migrations."""

import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends

from app.schemas.migration import MigrationInput, MigrationResult
from app.services.execution.registry import get_registry
from app.services.migration.openrouter import OpenRouterProvider
from app.services.migration.orchestrator import (
    MigrationOrchestrator,
    UnconfiguredLLMProvider,
)

router = APIRouter()


def get_orchestrator() -> MigrationOrchestrator:
    """Build the local-development orchestrator dependency."""
    output_root = Path(os.getenv("EUC_OUTPUT_ROOT", "output"))
    provider = OpenRouterProvider.from_environment() or UnconfiguredLLMProvider()
    return MigrationOrchestrator(provider, output_root, registry=get_registry(output_root))


@router.post("/api/migrations", response_model=MigrationResult)
def create_migration(
    migration_input: MigrationInput,
    orchestrator: Annotated[MigrationOrchestrator, Depends(get_orchestrator)],
) -> MigrationResult:
    """Run one migration synchronously."""
    return orchestrator.migrate(migration_input)

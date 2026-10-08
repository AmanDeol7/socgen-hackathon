"""Safe local Docker execution for already-generated standardized EUCs."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from app.schemas.execution import ExecutionResult
from app.services.execution.registry import (
    EucNotFoundError,
    EucRegistry,
    RegistryError,
)

_DEFAULT_TIMEOUT_SECONDS = 30.0
_SENSITIVE_LINE = re.compile(
    r"(?i)(secret|password|token|api[\s_-]?key|authorization|credential)"
)
_WINDOWS_DOCKER_PATHS = (
    Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    / "Docker"
    / "Docker"
    / "resources"
    / "bin"
    / "docker.exe",
    Path(os.environ.get("ProgramW6432", r"C:\Program Files"))
    / "Docker"
    / "Docker"
    / "resources"
    / "bin"
    / "docker.exe",
)
logger = logging.getLogger(__name__)


class ExecutionError(ValueError):
    """Raised when an EUC cannot be safely prepared for execution."""


class EucCertificationError(ExecutionError):
    """Raised when an EUC has not been approved for execution."""


class ExecutionService:
    """Execute registered EUCs through the local Docker CLI."""

    def __init__(
        self,
        output_root: str | Path,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        docker_command: str | None = None,
        registry: EucRegistry | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Execution timeout must be greater than zero.")
        self.output_root = Path(output_root)
        self.timeout_seconds = timeout_seconds
        self.docker_command = docker_command
        self.registry = registry or EucRegistry(output_root)

    @classmethod
    def from_environment(cls) -> ExecutionService:
        """Build the local service from non-secret environment configuration."""
        timeout_text = os.getenv(
            "EUC_EXECUTION_TIMEOUT_SECONDS",
            str(_DEFAULT_TIMEOUT_SECONDS),
        )
        try:
            timeout_seconds = float(timeout_text)
        except ValueError as error:
            raise ValueError(
                "EUC_EXECUTION_TIMEOUT_SECONDS must be a positive number."
            ) from error
        return cls(
            output_root=Path(os.getenv("EUC_OUTPUT_ROOT", "output")),
            timeout_seconds=timeout_seconds,
        )

    def execute(self, euc_name: str, input_data: dict) -> ExecutionResult:
        """Run one existing EUC and capture its Docker process result."""
        self.ensure_certified(euc_name)
        try:
            metadata = self.registry.get(euc_name)
        except EucNotFoundError:
            try:
                self.registry.register_existing(euc_name)
                metadata = self.registry.get(euc_name)
            except RegistryError as error:
                raise ExecutionError(str(error)) from error
        except RegistryError as error:
            raise ExecutionError(str(error)) from error
        image_name = metadata.image
        docker_command = self.docker_command or _resolve_docker_command()
        command = [docker_command, "run", "--rm", "-i", image_name]
        try:
            completed = subprocess.run(
                command,
                input=json.dumps(input_data, ensure_ascii=False),
                text=True,
                capture_output=True,
                check=False,
                timeout=self.timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                status="TIMED_OUT",
                euc_name=euc_name,
                exit_code=None,
                stdout="",
                stderr="EUC execution timed out.",
            )
        except OSError as error:
            logger.warning(
                "Docker subprocess could not be started (%s: %s).",
                type(error).__name__,
                _safe_os_error(error),
            )
            return ExecutionResult(
                status="FAILED",
                euc_name=euc_name,
                exit_code=None,
                stdout="",
                stderr="Unable to start the Docker execution.",
            )

        status = "COMPLETED" if completed.returncode == 0 else "FAILED"
        return ExecutionResult(
            status=status,
            euc_name=euc_name,
            exit_code=completed.returncode,
            stdout=_sanitize_output(completed.stdout),
            stderr=_sanitize_output(completed.stderr),
        )

    def ensure_certified(self, euc_name: str) -> None:
        """Reject uncertified artifacts before lifecycle tracking or Docker."""
        try:
            metadata = self.registry.get(euc_name)
        except EucNotFoundError:
            try:
                self.registry.register_existing(euc_name)
                metadata = self.registry.get(euc_name)
            except RegistryError:
                return
        except RegistryError:
            return
        try:
            metadata = self.registry.refresh_certification(euc_name)
        except RegistryError as error:
            raise EucCertificationError(
                "Unable to verify EUC certification against its generated files."
            ) from error
        if metadata.certification_status != "CERTIFIED":
            raise EucCertificationError(
                f"EUC '{euc_name}' is not certified for execution."
            )

def _sanitize_output(output: str) -> str:
    """Suppress lines that are likely to contain sensitive runtime values."""
    safe_lines = [
        "Execution output suppressed." if _SENSITIVE_LINE.search(line) else line
        for line in output.splitlines()
    ]
    return "\n".join(safe_lines)


def _resolve_docker_command() -> str:
    """Resolve Docker without accepting an executable path from the request."""
    docker_path = shutil.which("docker")
    if docker_path:
        return docker_path
    for candidate in _WINDOWS_DOCKER_PATHS:
        if candidate.is_file():
            return str(candidate)
    return "docker"


def _safe_os_error(error: OSError) -> str:
    """Return only non-sensitive process-start diagnostics for server logs."""
    if getattr(error, "winerror", None) == 2 or getattr(error, "errno", None) == 2:
        return "executable not found"
    return "process creation failed"

"""Deterministic local Docker image builds for generated EUCs."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

_IMAGE_NAME = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_IMAGE_TAG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
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


class DockerBuildError(ValueError):
    """Raised when Docker cannot build a generated EUC image."""


class DockerImageBuilder:
    """Build an image from a validated generated EUC directory."""

    def __init__(self, docker_command: str | None = None) -> None:
        self.docker_command = docker_command

    def build(self, build_directory: str | Path, image: str, version: str) -> None:
        """Build or replace ``image:version`` using the EUC directory as context."""
        if not _IMAGE_NAME.fullmatch(image):
            raise DockerBuildError("Docker image name is invalid.")
        if not _IMAGE_TAG.fullmatch(version):
            raise DockerBuildError("Docker image version is invalid.")

        directory = Path(build_directory).resolve()
        if not directory.is_dir() or not (directory / "Dockerfile").is_file():
            raise DockerBuildError("Docker build directory or Dockerfile is invalid.")

        docker_command = self.docker_command or _resolve_docker_command()
        if docker_command is None:
            raise DockerBuildError(
                "Docker executable is unavailable; install Docker Desktop and ensure its CLI is available."
            )

        image_reference = f"{image}:{version}"
        environment = os.environ.copy()
        executable = Path(docker_command)
        if executable.is_absolute():
            executable_directory = str(executable.parent)
            path_entries = environment.get("PATH", "").split(os.pathsep)
            if not any(
                entry.casefold() == executable_directory.casefold()
                for entry in path_entries
                if entry
            ):
                environment["PATH"] = os.pathsep.join(
                    [executable_directory, environment.get("PATH", "")]
                )
        subprocess_options = {
            "text": True,
            "capture_output": True,
            "shell": False,
            "stdin": subprocess.DEVNULL,
            "env": environment,
        }
        if sys.platform == "win32":
            subprocess_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            completed = subprocess.run(
                [
                    docker_command,
                    "build",
                    "--progress=plain",
                    "-t",
                    image_reference,
                    str(directory),
                ],
                check=False,
                **subprocess_options,
            )
        except OSError as error:
            raise DockerBuildError(
                "Docker executable could not be started."
            ) from error
        except subprocess.TimeoutExpired as error:
            raise DockerBuildError(
                "Docker image build timed out."
            ) from error

        if completed.returncode != 0:
            raise DockerBuildError(
                f"Docker image build failed for {image_reference} "
                f"(exit code {completed.returncode}). Check Docker availability "
                "and the generated EUC build files."
            )


def _resolve_docker_command() -> str | None:
    command = shutil.which("docker")
    if command:
        return command
    for candidate in _WINDOWS_DOCKER_PATHS:
        if candidate.is_file():
            return str(candidate)
    return None

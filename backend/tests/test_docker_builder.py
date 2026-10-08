"""Tests for deterministic migration-time Docker image builds."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.migration import docker_builder
from app.services.migration.docker_builder import DockerBuildError, DockerImageBuilder


def _build_context(tmp_path: Path) -> Path:
    context = tmp_path / "euc"
    context.mkdir()
    (context / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    return context


def test_build_uses_generated_context_and_image_tag(tmp_path: Path) -> None:
    context = _build_context(tmp_path)
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="built", stderr=""
    )
    with patch(
        "app.services.migration.docker_builder.subprocess.run",
        return_value=completed,
    ) as run:
        DockerImageBuilder("docker").build(context, "customer-greeting", "latest")

    command = run.call_args.args[0]
    assert command == [
        "docker",
        "build",
        "--progress=plain",
        "-t",
        "customer-greeting:latest",
        str(context.resolve()),
    ]
    assert run.call_args.kwargs["text"] is True
    assert run.call_args.kwargs["capture_output"] is True
    assert run.call_args.kwargs["check"] is False
    assert run.call_args.kwargs["shell"] is False
    assert run.call_args.kwargs["stdin"] is subprocess.DEVNULL
    assert run.call_args.kwargs["capture_output"] is True


@pytest.mark.parametrize(
    ("platform", "expect_creationflags"),
    [("win32", True), ("linux", False)],
)
def test_build_applies_windows_process_group_conditionally(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    expect_creationflags: bool,
) -> None:
    context = _build_context(tmp_path)
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    monkeypatch.setattr(docker_builder.sys, "platform", platform)
    with patch(
        "app.services.migration.docker_builder.subprocess.run",
        return_value=completed,
    ) as run:
        DockerImageBuilder("docker").build(context, "demo", "latest")

    kwargs = run.call_args.kwargs
    if expect_creationflags:
        assert kwargs["creationflags"] == subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        assert "creationflags" not in kwargs


def test_build_failure_does_not_expose_build_output(tmp_path: Path) -> None:
    context = _build_context(tmp_path)
    completed = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="secret=private", stderr="secret=private"
    )
    with (
        patch(
        "app.services.migration.docker_builder.subprocess.run",
        return_value=completed,
        ),
        pytest.raises(DockerBuildError, match="exit code 1") as error,
    ):
        DockerImageBuilder("docker").build(context, "demo", "latest")

    assert "private" not in str(error.value)


def test_build_rejects_unavailable_docker(tmp_path: Path, monkeypatch) -> None:
    context = _build_context(tmp_path)
    monkeypatch.setattr(
        "app.services.migration.docker_builder._resolve_docker_command",
        lambda: None,
    )

    with pytest.raises(DockerBuildError, match="unavailable"):
        DockerImageBuilder().build(context, "demo", "latest")


@pytest.mark.parametrize("image", ["../demo", "Demo", "demo:latest", ""])
def test_build_rejects_unsafe_image_names(tmp_path: Path, image: str) -> None:
    context = _build_context(tmp_path)
    with pytest.raises(DockerBuildError, match="image name is invalid"):
        DockerImageBuilder("docker").build(context, image, "latest")


@pytest.mark.parametrize("context_exists", [False, True])
def test_build_rejects_invalid_context_or_missing_dockerfile(
    tmp_path: Path, context_exists: bool
) -> None:
    context = tmp_path / "euc"
    if context_exists:
        context.mkdir()
    with pytest.raises(DockerBuildError, match="build directory or Dockerfile"):
        DockerImageBuilder("docker").build(context, "demo", "latest")

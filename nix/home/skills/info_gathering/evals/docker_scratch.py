"""Docker scratch space for eval agents.

Provides a per-run ephemeral container that the agent can exec into freely.
Using the scratch tool does not count as a game turn.
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

from pydantic import BaseModel

from nix.home.skills.info_gathering.evals.harness import ToolHandler, ToolParam, tool_def
from third_party.debian_slim.rlocations import IMAGE_TAG, LOAD_SCRIPT
from util.bazel.runfiles import get_required_path

logger = logging.getLogger(__name__)

# Output cap per stream (bytes, as string length) to avoid flooding context
_MAX_OUTPUT_CHARS = 8_000


class ScratchExecInput(BaseModel):
    cmd: list[str]
    timeout_ms: int = 30_000


SCRATCH_EXEC_TOOL: ToolParam = tool_def(
    "scratch_exec",
    (
        "Run a command inside your private scratch container. "
        "The cmd array is passed directly to Docker exec (no shell). "
        'For shell features use: ["sh", "-c", "..."]'
    ),
    ScratchExecInput,
)


class DockerScratchpad:
    """Per-run ephemeral Docker container for agent scratch work.

    Usage:
        with DockerScratchpad(image="debian-slim:test") as pad:
            result = pad.exec(["echo", "hello"])
    """

    def __init__(self, image: str) -> None:
        self._image = image
        self._container_id: str | None = None

    def __enter__(self) -> DockerScratchpad:
        result = subprocess.run(
            ["docker", "run", "-d", "--network=none", self._image, "sleep", "infinity"],
            capture_output=True,
            text=True,
            check=True,
        )
        self._container_id = result.stdout.strip()
        logger.info("Scratch container started: %s (image=%s)", self._container_id[:12], self._image)
        return self

    def __exit__(self, *_: Any) -> None:
        if self._container_id:
            subprocess.run(["docker", "rm", "-f", self._container_id], check=False, capture_output=True)
            logger.info("Scratch container removed: %s", self._container_id[:12])
            self._container_id = None

    def exec(self, cmd: list[str], *, timeout_ms: int = 30_000) -> dict[str, Any]:
        """Run cmd in the scratch container, return stdout/stderr/exit_code."""
        if self._container_id is None:
            raise RuntimeError("DockerScratchpad not started (use as context manager)")
        timeout_secs = timeout_ms / 1000
        try:
            result = subprocess.run(
                ["docker", "exec", self._container_id, *cmd],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_secs,
            )
            return {
                "stdout": result.stdout[-_MAX_OUTPUT_CHARS:],
                "stderr": result.stderr[-_MAX_OUTPUT_CHARS:],
                "exit_code": result.returncode,
                "timed_out": False,
            }
        except subprocess.TimeoutExpired:
            return {
                "stdout": "",
                "stderr": f"Command timed out after {timeout_secs}s",
                "exit_code": None,
                "timed_out": True,
            }


def make_scratch_handler(scratchpad: DockerScratchpad) -> ToolHandler:
    """Return a ToolHandler that dispatches scratch_exec calls to the given scratchpad."""

    def handle(tool_name: str, inp: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "scratch_exec":
            validated = ScratchExecInput.model_validate(inp)
            return scratchpad.exec(validated.cmd, timeout_ms=validated.timeout_ms)
        raise ValueError(f"Unknown tool: {tool_name!r}")

    return handle


def load_scratch_image() -> str:
    """Load the debian-slim image into the local Docker daemon and return its tag."""
    load_script = get_required_path(f"_main/{LOAD_SCRIPT}")
    result = subprocess.run(
        [str(load_script)],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "DOCKER_CLI_EXPERIMENTAL": "enabled"},
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to load scratch image: {result.stderr}")
    logger.info("Loaded scratch image: %s", IMAGE_TAG)
    return IMAGE_TAG

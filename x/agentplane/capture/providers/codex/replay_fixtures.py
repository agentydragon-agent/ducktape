"""Codex-specific pytest fixtures for native replay tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from util.bazel.runfiles import get_required_path
from x.agentplane.capture.providers import shared_capture
from x.agentplane.capture.providers.codex import scenarios
from x.agentplane.capture.replay import ReplayServer


@dataclass(frozen=True)
class CodexReplay:
    root: Path
    codex_home: Path
    binary: str
    capture_factory: Callable[[list[str], dict[str, str]], shared_capture.NativeCapture]
    environment_factory: Callable[..., dict[str, str]]

    def command(self, *, endpoint: str) -> list[str]:
        return scenarios.command(self.binary, endpoint=f"{endpoint}/v1")

    def environment(self, endpoint: str) -> dict[str, str]:
        return self.environment_factory(
            CODEX_HOME=str(self.codex_home), OPENAI_API_KEY="test-key", OPENAI_BASE_URL=f"{endpoint}/v1"
        )

    def capture(self, server: ReplayServer) -> shared_capture.NativeCapture:
        endpoint = f"http://127.0.0.1:{server.server_port}"
        return self.capture_factory(self.command(endpoint=endpoint), self.environment(endpoint))


@pytest.fixture
def codex_replay(
    capture_factory: Callable[[list[str], dict[str, str]], shared_capture.NativeCapture],
    environment_factory: Callable[..., dict[str, str]],
    tmp_path: Path,
) -> CodexReplay:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    return CodexReplay(
        root=tmp_path,
        codex_home=codex_home,
        binary=str(get_required_path("agentplane_codex_cli_linux_x64/bin/codex")),
        capture_factory=capture_factory,
        environment_factory=environment_factory,
    )

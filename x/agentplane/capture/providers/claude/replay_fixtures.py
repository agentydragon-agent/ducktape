"""Claude-specific pytest fixtures for native replay tests."""

from __future__ import annotations

import struct
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from util.bazel.runfiles import get_required_path
from x.agentplane.capture.providers.claude import scenarios
from x.agentplane.capture.providers.shared_capture import NativeCapture
from x.agentplane.capture.replay import ReplayServer


@dataclass(frozen=True)
class ClaudeReplay:
    root: Path
    config: Path
    binary: str
    capture_factory: Callable[[list[str], dict[str, str]], NativeCapture]
    environment_factory: Callable[..., dict[str, str]]

    def command(self, *, resume_id: str | None = None) -> list[str]:
        command = scenarios.command(
            self.binary, model="anthropic-max20/ant-messages/claude-haiku-4-5-20251001", resume_id=resume_id
        )
        return [_python_dynamic_loader(), *command]

    def environment(self, endpoint: str) -> dict[str, str]:
        return self.environment_factory(
            ANTHROPIC_AUTH_TOKEN="test-key", ANTHROPIC_BASE_URL=endpoint, CLAUDE_CONFIG_DIR=str(self.config)
        )

    def capture(self, server: ReplayServer, *, resume_id: str | None = None) -> NativeCapture:
        endpoint = f"http://127.0.0.1:{server.server_port}"
        capture = self.capture_factory(self.command(resume_id=resume_id), self.environment(endpoint))
        capture.frame_handler = _allow_permission
        return capture


@pytest.fixture
def claude_replay(
    capture_factory: Callable[[list[str], dict[str, str]], NativeCapture],
    environment_factory: Callable[..., dict[str, str]],
    tmp_path: Path,
) -> ClaudeReplay:
    config = tmp_path / ".claude"
    config.mkdir()
    return ClaudeReplay(
        root=tmp_path,
        config=config,
        binary=str(get_required_path("claude_code_cli_linux_x64/claude")),
        capture_factory=capture_factory,
        environment_factory=environment_factory,
    )


def _python_dynamic_loader() -> str:
    # TODO: run Claude in RBE without this Nix ELF-loader workaround.
    data = Path(sys.executable).resolve().read_bytes()
    if data[:4] != b"\x7fELF":
        raise RuntimeError("Bazel Python is not an ELF executable")
    program_offset = struct.unpack_from("<Q", data, 32)[0]
    program_size = struct.unpack_from("<H", data, 54)[0]
    program_count = struct.unpack_from("<H", data, 56)[0]
    for index in range(program_count):
        offset = program_offset + index * program_size
        if struct.unpack_from("<I", data, offset)[0] != 3:
            continue
        interpreter_offset = struct.unpack_from("<Q", data, offset + 8)[0]
        interpreter_size = struct.unpack_from("<Q", data, offset + 32)[0]
        return data[interpreter_offset : interpreter_offset + interpreter_size].rstrip(b"\0").decode()
    raise RuntimeError("Bazel Python has no ELF interpreter")


def _allow_permission(frame: dict[str, object]) -> dict[str, object] | None:
    request = frame.get("request")
    if not isinstance(request, dict) or request.get("subtype") != "can_use_tool":
        return None
    return {
        "type": "control_response",
        "response": {
            "subtype": "success",
            "request_id": frame["request_id"],
            "response": {"behavior": "allow", "updatedInput": request.get("input")},
        },
    }

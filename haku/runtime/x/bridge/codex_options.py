"""Codex app-server as a bridge backend: native process launch and executable resolution.

The Console-side adapter owns the JSON-RPC handshake, thread configuration, prompts and
projection. This module owns only what the shared runner needs: the exact app-server argv and the
binary that answers it. Native messages remain opaque ``HarnessFrame`` payloads to the runner.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from haku.runtime.x.bridge.backend import ProcessLaunch, child_environment
from haku.runtime.x.bridge.protocol import HarnessLaunch

EXECUTABLE_VARIABLE = "HAKU_CODEX_PATH"
_MCP_OVERRIDE = "mcp_servers="


@dataclass(frozen=True, slots=True)
class HttpMcpServer:
    """A streamable-HTTP MCP server Codex reaches with an inherited bearer variable."""

    url: str
    bearer_token_env_var: str


@dataclass(frozen=True, slots=True)
class CodexAppServerSession:
    """Everything the Console chooses about one Codex app-server process."""

    cwd: Path | None = None
    environment: Mapping[str, str] = field(default_factory=dict)
    mcp_servers: Mapping[str, HttpMcpServer] = field(default_factory=dict)


def _mcp_config(servers: Mapping[str, tuple[str, str | None]]) -> str:
    entries = []
    for name, (url, bearer_token_env_var) in sorted(servers.items()):
        fields = [f"url = {json.dumps(url)}"]
        if bearer_token_env_var is not None:
            fields.append(f"bearer_token_env_var = {json.dumps(bearer_token_env_var)}")
        entries.append(f"{json.dumps(name)} = {{ {', '.join(fields)} }}")
    return f"{_MCP_OVERRIDE}{{ {', '.join(entries)} }}"


def build_codex_launch(session: CodexAppServerSession, *, resume_from: int | None = None) -> HarnessLaunch:
    """Launch the pinned Codex binary as one newline-delimited stdio app-server."""
    arguments: list[str] = []
    if session.mcp_servers:
        arguments.extend(
            (
                "-c",
                _mcp_config(
                    {name: (server.url, server.bearer_token_env_var) for name, server in session.mcp_servers.items()}
                ),
            )
        )
    arguments.extend(("app-server", "--listen", "stdio://"))
    return HarnessLaunch(
        arguments=tuple(arguments),
        cwd=str(session.cwd) if session.cwd is not None else ".",
        environment=dict(session.environment),
        resume_from=resume_from,
    )


@dataclass(frozen=True, slots=True)
class CodexAppServerBackend:
    """Codex app-server, as the sandbox runner starts it and reads it back."""

    name: ClassVar[str] = "codex-app-server"
    executable: Path

    def resolve(self, launch: HarnessLaunch) -> ProcessLaunch:
        return ProcessLaunch(
            executable=self.executable,
            arguments=launch.arguments,
            cwd=launch.cwd,
            environment=child_environment(launch),
        )


def codex_app_server_backend(executable: Path | None = None) -> CodexAppServerBackend:
    """Codex at the image-selected path, or at *executable* for a test/local run."""
    return CodexAppServerBackend(
        executable=executable if executable is not None else Path(os.environ.get(EXECUTABLE_VARIABLE, "codex"))
    )

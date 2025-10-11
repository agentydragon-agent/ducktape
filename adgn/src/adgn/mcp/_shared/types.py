from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from adgn.mcp.exec_common.io_limits import TimeoutMs


class ExecInput(BaseModel):
    """Typed payload for container exec tool.

    Prefer passing cmd as a list to avoid shell quoting issues. Set shell=True to run via
    'sh -lc <cmd>' when providing a single string command assembled server-side.
    """

    cmd: list[str] = Field(
        description="Command to run; pass list to avoid shell quoting issues",
    )
    cwd: Path | None = Field(default=None, description="Working directory inside container")
    env: dict[str, str] | None = Field(
        default=None,
        description="Environment variables for the process",
    )
    user: str | None = Field(default=None, description="Username inside container")
    tty: bool = Field(default=False, description="Allocate a TTY for the process")
    shell: bool = Field(default=False, description="Run via sh -lc <cmd>")
    timeout_ms: TimeoutMs = Field(
        description="Timeout in milliseconds; sends TERM (exit_code becomes None)",
    )


class ExecResult(BaseModel):
    """Structured output for container exec tool.

    Returned as structuredContent by FastMCP when structured_output=True is set on the tool.
    """

    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str


class ContainerImageInfo(BaseModel):
    name: str | None = None
    id: str | None = None
    tags: list[str] | None = None


class NetworkMode(StrEnum):
    NONE = "none"
    BRIDGE = "bridge"
    HOST = "host"


class ContainerImageHistoryEntry(BaseModel):
    """One line from Docker image history (docker API).

    Docker engine returns keys with specific casing; we accept them via aliases and
    normalize to snake_case on our JSON output.
    """

    id: str | None = Field(default=None, alias="Id")
    created: int | None = Field(default=None, alias="Created")
    created_by: str | None = Field(default=None, alias="CreatedBy")
    tags: list[str] | None = Field(default=None, alias="Tags")
    size: int | None = Field(default=None, alias="Size")
    comment: str | None = Field(default=None, alias="Comment")


class ContainerInfo(BaseModel):
    """JSON shape for the runtime container.info resource.

    Returned by the runtime/docker exec servers as a single JSON part in ReadResourceResult.
    """

    image: ContainerImageInfo | dict
    container_id: str | None = None
    volumes: dict | list | None = None
    working_dir: str | None = None
    network_mode: NetworkMode | None = None
    image_history: list[ContainerImageHistoryEntry] | None = None
    ephemeral: bool | None = None


class SimpleOk(BaseModel):
    """Minimal ack type for tools that just signal success."""

    ok: bool = True

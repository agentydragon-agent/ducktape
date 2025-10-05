from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.client.stdio import StdioServerParameters
from pydantic import AliasChoices, BaseModel, Field


class StdioSpec(StdioServerParameters):
    transport: Literal["stdio"] = "stdio"
    # Optional initialize timeout in seconds (<=0 disables)
    init_timeout_secs: int | None = Field(
        default=None, description="Initialize timeout in seconds (<=0 disables)"
    )


class SseSpec(BaseModel):
    """Server-Sent Events transport (timeouts are in seconds).

    Field names encode units explicitly. For backward-compatibility on input, we accept
    legacy keys via validation aliases: `timeout` → `timeout_secs`, `sse_read_timeout` →
    `sse_read_timeout_secs`.
    """

    transport: Literal["sse"] = "sse"
    url: str
    headers: dict[str, str] | None = None
    # Seconds
    timeout_secs: int | None = Field(
        default=5,
        description="Connect/request timeout in seconds",
        validation_alias=AliasChoices("timeout_secs", "timeout"),
    )
    sse_read_timeout_secs: int | None = Field(
        default=60 * 5,
        description="Read timeout for SSE loop in seconds",
        validation_alias=AliasChoices("sse_read_timeout_secs", "sse_read_timeout"),
    )
    init_timeout_secs: int | None = Field(
        default=None, description="Initialize timeout in seconds (<=0 disables)"
    )


class InprocFactorySpec(BaseModel):
    transport: Literal["inproc"] = "inproc"
    # Dotted path to a callable that returns a FastMCP server: 'pkg.mod:factory' or 'pkg.mod.factory'
    factory: str
    args: list[Any] | None = None
    kwargs: dict[str, Any] | None = None
    init_timeout_secs: int | None = Field(
        default=None, description="Initialize timeout in seconds (<=0 disables)"
    )


McpServerSpec = Annotated[
    StdioSpec | SseSpec | InprocFactorySpec,
    Field(discriminator="transport"),
]

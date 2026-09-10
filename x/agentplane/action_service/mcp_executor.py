"""The first concrete Executor wiring gate adapter: one ActionGroup backed by one MCP server.

Owns a persistent connection to the configured MCP server, mirrors its `tools/list` into the
bound `ActionGroup`'s catalog, and initiates `tools/call` itself — the Agent/harness never gets
a direct MCP client. See plans/operations_and_access.md § "Action groups, MCP discovery, and
backend ownership".
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any, Literal, cast

import httpx
import jsonschema
import mcp.types
from fastmcp.client import Client, ClientTransport
from fastmcp.client.messages import MessageHandler
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from x.agentplane.action_service.catalog import ActionDefinition, ActionGroup, Key, McpExecutorBinding
from x.agentplane.action_service.mcp_linkage import McpLinkageAuthority
from x.agentplane.action_service.models import ExecutionLease, ExecutionRequest, ExecutionResult, ExecutionState
from x.agentplane.action_service.service import ExecutionOutcomeUnknownError

logger = logging.getLogger(__name__)

DEFAULT_CATALOG_REFRESH_INTERVAL = timedelta(minutes=5)
_KEY_ADAPTER = TypeAdapter(Key)


class McpStdioServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transport: Literal["stdio"] = "stdio"
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None


class McpHttpServerConfig(BaseModel):
    """Credentialless endpoint; authentication and header forwarding are not configurable here."""

    model_config = ConfigDict(extra="forbid")

    transport: Literal["streamable-http"]
    url: AnyHttpUrl
    server_id: Key | None = None
    auth: Literal["none", "oauth"] = "none"

    @model_validator(mode="after")
    def require_linkage_server(self) -> McpHttpServerConfig:
        if self.auth == "oauth" and self.server_id is None:
            raise ValueError("OAuth MCP HTTP config requires server_id")
        return self

    @field_validator("url")
    @classmethod
    def validate_endpoint(cls, url: AnyHttpUrl) -> AnyHttpUrl:
        if url.username is not None or url.password is not None or url.fragment is not None or url.query is not None:
            raise ValueError("MCP endpoint must not contain userinfo, a query, or a fragment")
        return url


McpServerConfig = McpStdioServerConfig | McpHttpServerConfig
_SERVER_CONFIG_ADAPTER: TypeAdapter[McpServerConfig] = TypeAdapter(McpServerConfig)


class _ToolListChangeHandler(MessageHandler):
    def __init__(self, changed: asyncio.Event) -> None:
        self._changed = changed

    async def on_tool_list_changed(self, message: mcp.types.ToolListChangedNotification) -> None:
        del message
        self._changed.set()


class _LinkageBearerAuth(httpx.Auth):
    requires_response_body = False

    def __init__(self, linkage: McpLinkageAuthority, server_id: str) -> None:
        self._linkage = linkage
        self._server_id = server_id

    async def async_auth_flow(self, request: httpx.Request):
        token = await self._linkage.access_token_for_execution(self._server_id)
        request.headers["Authorization"] = f"Bearer {token}"
        yield request


class McpActionGroupExecutor:
    """Implements `Executor` for exactly one `ActionGroup` backed by one MCP server connection."""

    def __init__(
        self,
        group_key: str,
        group: ActionGroup,
        transport: ClientTransport | Any,
        *,
        catalog_refresh_interval: timedelta = DEFAULT_CATALOG_REFRESH_INTERVAL,
    ) -> None:
        self._group_key = group_key
        self._group = group
        self._catalog_refresh_interval = catalog_refresh_interval
        self._tool_list_changed = asyncio.Event()
        self._client = Client(transport, message_handler=_ToolListChangeHandler(self._tool_list_changed))
        self._stack = AsyncExitStack()
        self._refresh_task: asyncio.Task[None] | None = None
        self._requires_linkage = False

    @property
    def requires_linkage(self) -> bool:
        return self._requires_linkage

    @classmethod
    def from_group(
        cls,
        group_key: str,
        group: ActionGroup,
        *,
        catalog_refresh_interval: timedelta = DEFAULT_CATALOG_REFRESH_INTERVAL,
    ) -> McpActionGroupExecutor:
        if not isinstance(group.executor, McpExecutorBinding):
            raise ValueError("unsupported executor binding; expected MCP")
        config = _SERVER_CONFIG_ADAPTER.validate_python(group.executor.config)
        transport: ClientTransport
        if isinstance(config, McpStdioServerConfig):
            transport = StdioTransport(config.command, config.args, env=config.env or None, cwd=config.cwd)
        else:
            transport = StreamableHttpTransport(config.url, auth=None)
        return cls(group_key, group, transport, catalog_refresh_interval=catalog_refresh_interval)

    @classmethod
    def from_group_with_linkage(
        cls,
        group_key: str,
        group: ActionGroup,
        linkage: McpLinkageAuthority,
        *,
        catalog_refresh_interval: timedelta = DEFAULT_CATALOG_REFRESH_INTERVAL,
    ) -> McpActionGroupExecutor:
        if not isinstance(group.executor, McpExecutorBinding):
            raise ValueError("unsupported executor binding; expected MCP")
        config = _SERVER_CONFIG_ADAPTER.validate_python(group.executor.config)
        if not isinstance(config, McpHttpServerConfig) or config.auth != "oauth" or config.server_id is None:
            return cls.from_group(group_key, group, catalog_refresh_interval=catalog_refresh_interval)
        transport = StreamableHttpTransport(config.url, auth=_LinkageBearerAuth(linkage, config.server_id))
        executor = cls(group_key, group, transport, catalog_refresh_interval=catalog_refresh_interval)
        executor._requires_linkage = True
        return executor

    async def start(self) -> None:
        self._group.available = False
        self._group.actions = {}
        await self._stack.enter_async_context(self._client)
        await self.refresh_catalog()
        self._refresh_task = asyncio.create_task(self._refresh_loop(), name=f"mcp-executor-refresh-{self._group_key}")

    async def close(self) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            await asyncio.gather(self._refresh_task, return_exceptions=True)
            self._refresh_task = None
        await self._stack.aclose()

    async def _refresh_loop(self) -> None:
        while True:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._tool_list_changed.wait(), timeout=self._catalog_refresh_interval.total_seconds()
                )
            self._tool_list_changed.clear()
            try:
                await self.refresh_catalog()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("periodic MCP catalog refresh failed; will retry")

    async def refresh_catalog(self) -> None:
        try:
            tools = await self._client.list_tools()
        except Exception:
            logger.warning("MCP tools/list failed; %s marked unavailable", self._group_key)
            self._group.available = False
            self._group.actions = {}
            return
        actions: dict[str, ActionDefinition] = {}
        for tool in tools:
            try:
                key = _KEY_ADAPTER.validate_python(tool.name)
            except ValidationError:
                logger.warning("MCP tool name %r does not fit the catalog key pattern; skipping", tool.name)
                continue
            try:
                jsonschema.validators.validator_for(tool.inputSchema).check_schema(tool.inputSchema)
                if key in actions:
                    raise ValueError("duplicate MCP tool name")
                actions[key] = ActionDefinition(
                    description=tool.description or f"MCP tool {tool.name}", input_schema=tool.inputSchema
                )
            except (jsonschema.SchemaError, ValueError):
                logger.warning("MCP catalog invalid; %s marked unavailable", self._group_key)
                self._group.available = False
                self._group.actions = {}
                return
        self._group.actions = actions
        self._group.available = True

    async def execute(self, request: ExecutionRequest, lease: ExecutionLease) -> ExecutionResult:
        group_key, name = request.action.group, request.action.name
        if group_key != self._group_key:
            return ExecutionResult(
                state=ExecutionState.FAILED,
                error={"kind": "unknown_action", "message": "action is not owned by this group"},
            )

        try:
            tools = await self._client.list_tools()
        except Exception:
            logger.warning("MCP tools/list failed before dispatch; refusing without calling the backend")
            return ExecutionResult(
                state=ExecutionState.FAILED,
                error={"kind": "mcp_unavailable", "message": "could not verify the current tool schema"},
            )

        tool = next((tool for tool in tools if tool.name == name), None)
        if tool is None:
            return ExecutionResult(
                state=ExecutionState.FAILED,
                error={"kind": "unknown_action", "message": "action is no longer offered by the backend"},
            )

        try:
            jsonschema.validate(request.arguments, tool.inputSchema)
        except jsonschema.SchemaError:
            return ExecutionResult(
                state=ExecutionState.FAILED,
                error={"kind": "mcp_invalid_schema", "message": "backend tool schema is invalid"},
            )
        except jsonschema.ValidationError:
            return ExecutionResult(
                state=ExecutionState.FAILED,
                error={
                    "kind": "incompatible_action_schema",
                    "message": "arguments no longer match the current tool schema",
                },
            )

        try:
            result = await self._client.call_tool(name, request.arguments, raise_on_error=False)
        except Exception as error:
            raise ExecutionOutcomeUnknownError(f"MCP tools/call transport failure for {name}") from error

        if result.is_error:
            return ExecutionResult(
                state=ExecutionState.FAILED, error={"kind": "mcp_tool_error", "message": "MCP tool reported an error"}
            )
        return ExecutionResult(state=ExecutionState.SUCCEEDED, result=_safe_result(result))


def _safe_result(result: Any) -> JsonValue:
    if result.structured_content is not None:
        return cast(JsonValue, result.structured_content)
    texts: list[JsonValue] = [block.text for block in result.content if isinstance(block, mcp.types.TextContent)]
    return {"content": texts}

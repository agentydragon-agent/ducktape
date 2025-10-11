from __future__ import annotations

from fastmcp.client import Client
from fastmcp.mcp_config import MCPServerTypes
from mcp import types as mcp_types
from pydantic import BaseModel, Field, TypeAdapter

from adgn.mcp._shared.client_helpers import call_simple_ok
from adgn.mcp._shared.constants import COMPOSITOR_ADMIN_SERVER_NAME
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp._shared.resources import read_text_json
from adgn.mcp._shared.uris import (
    parse_compositor_state_server,
)
from adgn.mcp.snapshots import ServerEntry as CompositorStateValue


class _AttachServerArgs(BaseModel):
    name: str = Field(description="Mount name (must be unique and not contain '__')")
    spec: MCPServerTypes


class _DetachServerArgs(BaseModel):
    name: str


class CompositorAdminClient:
    """Typed client for the compositor_admin server tools.

    Expects a Client connected to the Compositor front door. Calls use fully
    namespaced tool names (mcp__compositor_admin__<tool>).
    """

    def __init__(self, client: Client) -> None:
        self._client = client
        self._attach_name = build_mcp_function(COMPOSITOR_ADMIN_SERVER_NAME, "attach_server")
        self._detach_name = build_mcp_function(COMPOSITOR_ADMIN_SERVER_NAME, "detach_server")

    @property
    def client(self) -> Client:
        return self._client

    async def attach_server(self, *, name: str, spec: MCPServerTypes) -> None:
        args = _AttachServerArgs(name=name, spec=spec)
        await call_simple_ok(self._client, name=self._attach_name, arguments=args.model_dump())

    async def detach_server(self, *, name: str) -> None:
        args = _DetachServerArgs(name=name)
        await call_simple_ok(self._client, name=self._detach_name, arguments=args.model_dump())


class CompositorMetaClient:
    """Typed client for compositor_meta read-only resources (per-server state).

    Provides list_states() to read the current server entries via resource URIs.
    """

    def __init__(self, client: Client) -> None:
        self._client = client

    @property
    def client(self) -> Client:
        return self._client

    async def list_states(self) -> dict[str, CompositorStateValue]:
        # Enumerate per-server state resources and read each typed value.
        # Filter to compositor_meta state resources using canonical helpers.
        resources = await self._client.list_resources()
        out: dict[str, CompositorStateValue] = {}
        for r in resources:
            if not isinstance(r, mcp_types.Resource):
                raise TypeError(
                    f"list_resources returned unsupported item type: {type(r).__name__}"
                )
            uri_str = str(r.uri)
            name = parse_compositor_state_server(uri_str)
            if name is None:
                continue
            raw = await read_text_json(self._client.session, uri_str)
            state: CompositorStateValue = TypeAdapter(CompositorStateValue).validate_python(raw)
            out[name] = state
        return out


# Internal helper; prefer explicit imports

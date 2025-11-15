from __future__ import annotations

from fastmcp.client import Client
from fastmcp.mcp_config import MCPServerTypes
from pydantic import BaseModel, Field

from adgn.mcp._shared.client_helpers import call_simple_ok
from adgn.mcp._shared.constants import COMPOSITOR_ADMIN_SERVER_NAME
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.snapshots import ServerEntry


class _AttachServerArgs(BaseModel):
    name: str = Field(description="Mount name (must be unique and not contain '__')")
    spec: MCPServerTypes


class _DetachServerArgs(BaseModel):
    name: str


class CompositorAdminClient:
    """Typed client for the compositor_admin server tools.

    Expects a Client connected to the Compositor front door. Calls use fully
    namespaced tool names ({server}_{tool}).
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

    async def list_states(self) -> dict[str, ServerEntry]:
        comp = getattr(getattr(self._client, "transport", None), "server", None)
        if not isinstance(comp, Compositor):
            raise RuntimeError("CompositorMetaClient requires an in-process Compositor transport")
        entries = await comp.server_entries()
        return dict(entries)


# Internal helper; prefer explicit imports

"""Matrix control MCP: yield-only control, no network I/O.

Purpose
- Provide a small control-plane for Matrix-driven agents that do I/O via
  docker_exec + CLI tools. The agent can:
  - get_state() → obtain current sync cursor (since) and last seen event id
  - yield(since, last_event_id?) → update cursor and end the turn via UiBus

No Matrix network calls occur inside this server — it is transport-agnostic and
purely local state + UI bus signaling.
"""

from __future__ import annotations

from pydantic import BaseModel

from adgn.agent.server.bus import ServerBus, UiEndTurn
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP


class YieldInput(BaseModel):
    pass


def make_matrix_control_server(name: str, bus: ServerBus) -> NotifyingFastMCP:
    mcp = NotifyingFastMCP(name, instructions=("Matrix control: yield-only control to signal end of turn."))

    @mcp.flat_model()
    def do_yield(input: YieldInput) -> UiEndTurn:
        """End the current turn. The runner will wake you on new DMs."""
        bus.push_end_turn()
        return UiEndTurn()

    return mcp


async def attach_matrix_control(comp: Compositor, bus: ServerBus, *, name: str = "matrix_control"):
    """Attach matrix control MCP in-proc (encapsulated)."""
    server = make_matrix_control_server(name, bus)
    await comp.mount_inproc(name, server)
    return server

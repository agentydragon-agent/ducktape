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
from adgn.mcp._shared.fastmcp_helpers import SafeFastMCP, mcp_flat_model


class YieldInput(BaseModel):
    pass


def make_matrix_control_mcp(name: str, bus: ServerBus) -> SafeFastMCP:
    mcp = SafeFastMCP(
        name,
        instructions=("Matrix control: call yield() to signal end of turn."),
    )

    @mcp_flat_model(
        mcp,
        name="yield",
        title="Yield turn",
        description=("End the current turn. The runner will wake you on new DMs."),
        structured_output=True,
    )
    def do_yield(input: YieldInput) -> UiEndTurn:
        bus.push_end_turn()
        return UiEndTurn()

    return mcp

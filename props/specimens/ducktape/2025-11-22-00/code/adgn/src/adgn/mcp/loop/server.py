from __future__ import annotations

from pydantic import BaseModel

from adgn.mcp._shared.types import SimpleOk
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP


class YieldTurnArgs(BaseModel):
    pass


def make_loop_server(name: str = "loop") -> NotifyingFastMCP:
    """Create a minimal loop-control MCP server.

    Tools are self-describing via MCP; avoid duplicating per-tool instructions here.
    """
    mcp = NotifyingFastMCP(name, instructions=("Loop control tools for orchestrator/agent turn coordination."))

    @mcp.flat_model()
    async def yield_turn(_: YieldTurnArgs) -> SimpleOk:
        # Orchestration semantics are owned by the runtime/handlers. The tool is a
        # neutral signal; the agent loop interprets it as yield/end-turn.
        return SimpleOk(ok=True)

    return mcp

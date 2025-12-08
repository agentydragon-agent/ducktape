from __future__ import annotations

from adgn.mcp._shared.types import SimpleOk
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel


class YieldTurnArgs(OpenAIStrictModeBaseModel):
    pass


def make_loop_server(name: str = "loop") -> EnhancedFastMCP:
    """Create a minimal loop-control MCP server.

    Tools are self-describing via MCP; avoid duplicating per-tool instructions here.
    """
    mcp = EnhancedFastMCP(name, instructions=("Loop control tools for orchestrator/agent turn coordination."))

    @mcp.flat_model()
    async def yield_turn(_: YieldTurnArgs) -> SimpleOk:
        # Orchestration semantics are owned by the runtime/handlers. The tool is a
        # neutral signal; the agent loop interprets it as yield/end-turn.
        return SimpleOk(ok=True)

    return mcp

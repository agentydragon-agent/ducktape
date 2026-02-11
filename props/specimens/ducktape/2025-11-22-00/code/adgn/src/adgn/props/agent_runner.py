from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import time

from fastmcp.client import Client
from fastmcp.server import FastMCP

from adgn.agent.agent import MiniCodex, TranscriptItem
from adgn.agent.agent_progress import OneLineProgressHandler
from adgn.agent.reducer import AutoHandler
from adgn.agent.transcript_handler import TranscriptHandler
from adgn.mcp.compositor.server import Compositor
from adgn.openai_utils.model import OpenAIModelProto


@dataclass
class AgentResult:
    final_text: str
    transcript: list[TranscriptItem]


async def run_prompt_async(
    prompt: str,
    model: str,
    server_factories: Mapping[str, Callable[..., FastMCP]],
    client: OpenAIModelProto,
    capture_transcript: bool = True,
    system_prompt: str = "You are a code agent. Be concise.",
) -> AgentResult:
    """Run the prompt using MiniCodex + MCP specs and return an AgentResult.

    - `servers` is a mapping server_name -> FastMCP (as produced by properties_docker_spec or builders)
    - This is the low-level primitive for running prompts through MCP-backed MiniCodex.
    - Returns transcript (list) and final_text (string).
    """
    transcript: list[TranscriptItem] = []
    comp = Compositor("compositor")
    for name, factory in server_factories.items():
        server = factory()
        await comp.mount_inproc(name, server)
    # Quiet, single-line progress by default (DisplayEventsHandler available for verbose UI)
    # Per-run transcript directory
    run_dir = Path.cwd() / "logs" / "mini_codex" / "agent_runner"
    run_dir = run_dir / f"run_{int(time.time())}_{os.getpid()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    async with Client(comp) as mcp_client:
        agent = await MiniCodex.create(
            model=model,
            mcp_client=mcp_client,
            system=system_prompt,
            client=client,
            handlers=[AutoHandler(), OneLineProgressHandler(), TranscriptHandler(dest_dir=run_dir)],
        )
        res_any = await agent.run(prompt)

    return AgentResult(final_text=res_any.text, transcript=transcript)

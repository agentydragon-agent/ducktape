from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import time

from adgn.agent.agent import MiniCodex, TranscriptItem
from adgn.agent.agent_progress import OneLineProgressHandler
from adgn.agent.loggers import TranscriptLoggerHandler
from adgn.agent.mcp_manager import McpManager
from adgn.agent.reducer import AutoHandler
from adgn.mcp.types import ServerSlotSpec
from adgn.openai_utils.model import OpenAIModelProto


@dataclass
class AgentResult:
    final_text: str
    transcript: list[TranscriptItem]


async def run_prompt_async(
    prompt: str,
    model: str,
    specs: Mapping[str, ServerSlotSpec],
    client: OpenAIModelProto,
    capture_transcript: bool = True,
    system_prompt: str = "You are a code agent. Be concise.",
) -> AgentResult:
    """Run the prompt using MiniCodex + MCP specs and return an AgentResult.

    - `specs` is a mapping server_name -> ServerSlotSpec (as produced by properties_docker_spec)
    - This is the low-level primitive for running prompts through MCP-backed MiniCodex.
    - Returns transcript (list) and final_text (string).
    """
    transcript: list[TranscriptItem] = []
    async with McpManager({}) as mcp:
        for name, slot in specs.items():
            await mcp.attach_server(name, slot)
        # Quiet, single-line progress by default (DisplayEventsHandler available for verbose UI)
        # Per-run transcript directory
        run_dir = Path.cwd() / "logs" / "mini_codex" / "agent_runner"
        run_dir = run_dir / f"run_{int(time.time())}_{os.getpid()}"
        run_dir.mkdir(parents=True, exist_ok=True)
        agent = await MiniCodex.create(
            model=model,
            mcp=mcp,
            system=system_prompt,
            client=client,
            handlers=[
                AutoHandler(),
                OneLineProgressHandler(),
                TranscriptLoggerHandler(run_dir),
            ],
        )
        res_any = await agent.run(prompt)

    # MiniCodex.run returns AgentResult with a text field
    final_text = res_any.text  # type: ignore[attr-defined]

    return AgentResult(final_text=final_text, transcript=transcript)

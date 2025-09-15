from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping
import os
import time
from pathlib import Path

from openai import AsyncOpenAI
from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.mcp_manager import McpManager
from adgn_llm.mcp.types import ServerSlotSpec
from adgn_llm.mini_codex.aggregating_handler import AutoHandler
from adgn_llm.mini_codex.agent_progress import OneLineProgressHandler
from adgn_llm.mini_codex.loggers import TranscriptLoggerHandler


@dataclass
class AgentResult:
    final_text: str
    transcript: List[Dict[str, Any]]  # raw trajectory pieces (may be dicts/messages)


async def run_prompt_async(
    prompt: str,
    model: str,
    specs: Mapping[str, ServerSlotSpec],
    client: AsyncOpenAI,
    capture_transcript: bool = True,
    system_prompt: str = "You are a code agent. Be concise.",
) -> AgentResult:
    """Run the prompt using MiniCodex + MCP specs and return an AgentResult.

    - `specs` is a mapping server_name -> ServerSlotSpec (as produced by properties_docker_spec)
    - This is the low-level primitive for running prompts through MCP-backed MiniCodex.
    - Returns transcript (list) and final_text (string).
    """
    transcript: List[Dict[str, Any]] = []
    async with McpManager(dict(specs)) as mcp:
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
            handlers=[AutoHandler(), OneLineProgressHandler(), TranscriptLoggerHandler(run_dir)],
        )
        res_any = await agent.run(prompt)

    # res_any may be an AsyncIterator of dicts or a single response object
    final_text = ""
    if hasattr(res_any, "__aiter__"):
        last = None
        async for piece in res_any:  # type: ignore
            if capture_transcript:
                transcript.append(dict(piece))
            last = piece
        if isinstance(last, dict):
            final_text = str((last.get("text") or "")).strip()
        else:
            final_text = str(getattr(last, "text", "") or "").strip()
    else:
        final_text = str(getattr(res_any, "text", "") or "").strip()
        if capture_transcript and hasattr(res_any, "choices"):
            # best-effort: include top-level choices
            transcript.append({"choices": getattr(res_any, "choices", None)})

    return AgentResult(final_text=final_text, transcript=transcript)

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from openai import AsyncOpenAI
from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.mcp_manager import McpManager
from adgn_llm.mcp.types import ServerSlotSpec
from adgn_llm.properties.docker_env import PropertiesDockerWiring


@dataclass
class AgentResult:
    final_text: str
    transcript: List[Dict[str, Any]]  # raw trajectory pieces (may be dicts/messages)
    parsed: Optional[Any] = None  # optional parsed JSON result if applicable


async def run_prompt_async(
    prompt: str,
    model: str,
    specs: Mapping[str, ServerSlotSpec],
    client: AsyncOpenAI,
    capture_transcript: bool = True,
) -> AgentResult:
    """Run the prompt using MiniCodex + MCP specs and return an AgentResult.

    - `specs` is a mapping server_name -> ServerSlotSpec (as produced by properties_docker_spec)
    - This is the low-level primitive for running prompts through MCP-backed MiniCodex.
    - Returns transcript (list) and final_text (string). Attempts to JSON-parse final_text into `parsed`.
    """
    if client is None:
        raise ValueError("client must be provided by CLI entry point")
    transcript: List[Dict[str, Any]] = []
    async with McpManager(dict(specs)) as mcp:
        agent = await MiniCodex.create(model=model, mcp=mcp, system="You are a code agent. Be concise.", client=client)
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

    parsed = None
    # If final_text looks like JSON, try parse
    s = final_text.strip()
    if s.startswith("{") or s.startswith("["):
        try:
            parsed = json.loads(s)
        except Exception:
            parsed = None

    return AgentResult(final_text=final_text, transcript=transcript, parsed=parsed)


# Synchronous wrappers removed: callers should run the async functions from the process entrypoint
# (e.g., in CLI main or test harness) using asyncio.run(...) so we keep event loop control close to main.
# Use run_prompt_async and run_prompt_with_wiring_async directly.


# Convenience runners that build MCP specs from a hydrated workspace wiring
async def run_prompt_with_wiring_async(
    prompt: str,
    model: str,
    wiring: PropertiesDockerWiring,
    *,
    client: AsyncOpenAI,
    capture_transcript: bool = True,
) -> AgentResult:
    specs = {wiring.server_name: wiring.server_spec}
    return await run_prompt_async(prompt, model, specs, client=client, capture_transcript=capture_transcript)


# Note: higher-level helpers (run_check/run_specimen) should live in a separate eval/runner module
# that composes prompt_builder + agent_runner, and returns structured outputs (FixReport, GradeSummary, etc.).

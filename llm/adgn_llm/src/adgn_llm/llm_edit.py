"""
Scaffold: adgn_llm_edit (MiniCodex-based)

This is a scaffold reimplementation of the adgn-llm-edit style tool, built on top of
src/adgn_llm/mini_codex/agent.py (MiniCodex agent, Responses API first).

Notes / Design:
- Uses MiniCodex as the orchestration layer (system instructions, tool policy, MCP tool wiring)
- Editing operations should be exposed as tools (read_line_range, replace_text, save_file, ...)
- Use structured results (Pydantic) for tool outputs; avoid string-parsing for success/failure
- Centralize file-type detection + syntax checks (python-only for now; unknown => no check)
- Future: allow the LLM to retry after syntax failure; provide an explicit syntax_check tool

This file intentionally contains TODOs and the minimal runnable skeleton to be filled out.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from pathlib import Path

import openai

from .mcp.editor_server import EditorServer
from .mini_codex.agent import MiniCodex, ToolMap


async def async_main() -> int:
    p = argparse.ArgumentParser("adgn_llm_edit")
    p.add_argument("file_path", help="Path to file to edit")
    p.add_argument("prompt", help="Editing prompt")
    p.add_argument("--model", default="o4-mini")
    args = p.parse_args()
    client = openai.OpenAI()
    editor_srv = EditorServer(Path(args.file_path))

    # Provide as a local server to MiniCodex via ToolMap (server name -> LocalServer)
    tools: ToolMap = {"editor": editor_srv}

    agent = await MiniCodex.start(
        model=args.model,
        tools=tools,
        system=(
            "You are a code editor assistant. Use tools to read/modify/save files.\n"
            "Operate on the provided file only. Prefer precise replace_text edits.\n"
            "Finish with done(success, report)."
        ),
        client=client,
    )
    res = await agent.run(
        f"Edit file: {args.file_path}\nGoal: {args.prompt}\n",
        stream=False,
    )
    # Print assistant text so caller sees the reasoning/summary; tool outcomes included in sequence
    if isinstance(res, dict) or hasattr(res, "text"):
        with contextlib.suppress(Exception):
            print(res.text)
    # Success if the last tool_output for editor/done indicates success, otherwise 0 anyway (the model may not call done)
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()

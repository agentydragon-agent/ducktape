"""
adgn_llm_edit

Notes / Design:
- Uses MiniCodex as the orchestration layer (system instructions, tool policy, MCP tool wiring)
- Editing operations should be exposed as tools (read_line_range, replace_text, save_file, ...)
- Use structured results (Pydantic) for tool outputs; avoid string-parsing for success/failure
- Centralize file-type detection + syntax checks (python-only for now; unknown => no check)
- Future: allow the LLM to retry after syntax failure; provide an explicit syntax_check tool
"""

from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Annotated

from fastmcp.client import Client
import typer

from adgn.agent.agent import MiniCodex
from adgn.agent.display import DisplayEventsHandler
from adgn.agent.loop_control import RequireAnyTool
from adgn.agent.transcript_handler import TranscriptHandler
from adgn.mcp._shared.constants import EDITOR_SERVER_NAME
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.editor_server import make_editor_server
from adgn.openai_utils import client_factory
from adgn.openai_utils.model import OpenAIModelProto
from adgn.openai_utils.types import ReasoningEffort, ReasoningSummary


async def _execute(
    *,
    file_path: Path,
    prompt: str,
    model: str,
    reasoning_effort: ReasoningEffort | None,
    reasoning_summary: ReasoningSummary | None,
    client: OpenAIModelProto,
) -> int:
    # Validate input path
    target_path = file_path
    if not target_path.is_file():
        print(f"Error: {target_path} is not a file")
        return 2

    # Folded context: per-agent MCP lifetime + agent lifetime
    async with Compositor() as comp:
        await comp.mount_inproc(EDITOR_SERVER_NAME, make_editor_server(target_path, name=EDITOR_SERVER_NAME))

        # Create a per-run transcript directory (aligned with MiniCodex defaults)
        run_dir = Path.cwd() / "logs" / "mini_codex" / "llm_edit"
        run_dir = run_dir / f"run_{int(time.time())}_{os.getpid()}"
        run_dir.mkdir(parents=True, exist_ok=True)

        async with Client(comp) as mcp_client:
            agent = await MiniCodex.create(
                mcp_client=mcp_client,
                system=(
                    "You are a code editor assistant. Use tools to read/modify/save files.\n"
                    "Operate on the provided file only. Prefer precise replace_text edits.\n"
                    "Finish with done(success, report)."
                ),
                client=client,
                reasoning_effort=reasoning_effort,
                reasoning_summary=reasoning_summary,
                handlers=[DisplayEventsHandler(), TranscriptHandler(events_path=run_dir / "events.jsonl")],
                tool_policy=RequireAnyTool(),
            )
            res = await agent.run(f"Edit file: {target_path}\nGoal: {prompt}\n")
            print(res.text)
            return 0


app = typer.Typer(help="LLM-powered single-file editor", add_completion=False)


@app.command()
async def edit(
    file_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True, help="Path to file to edit")],
    prompt: Annotated[str, typer.Argument(help="Editing prompt")],
    model: Annotated[str, typer.Option("--model", help="Model name")] = "o4-mini",
    reasoning_effort: Annotated[
        ReasoningEffort | None, typer.Option(help="Reasoning effort for reasoning-capable models", case_sensitive=False)
    ] = None,
    reasoning_summary: Annotated[
        ReasoningSummary | None, typer.Option(help="Emit reasoning summaries", case_sensitive=False)
    ] = None,
) -> None:
    client = client_factory.build_client(model)
    code = await _execute(
        file_path=file_path,
        prompt=prompt,
        model=model,
        reasoning_effort=reasoning_effort,
        reasoning_summary=reasoning_summary,
        client=client,
    )
    raise typer.Exit(code)


def main(argv: list[str] | None = None) -> None:
    # Typer entry; keep argv passthrough to avoid touching sys in tests
    if argv is None:
        app()
    else:
        app(args=argv)


if __name__ == "__main__":
    main()

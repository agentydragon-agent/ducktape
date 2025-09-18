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

import asyncio
import os
from pathlib import Path
import time
from typing import cast

import openai
from openai.types.shared_params import ReasoningEffort as SDKReasoningEffort
import typer

from adgn.llm.mini_codex.aggregating_handler import AutoHandler
from adgn.llm.mini_codex.event_renderer import DisplayEventsHandler
from adgn.llm.mini_codex.loggers import TranscriptLoggerHandler

from .mcp.editor_server import make_editor_mcp
from .mcp.inproc_transport import make_inproc_slot_spec
from .mini_codex.agent import MiniCodex
from .mini_codex.mcp_manager import McpManager
from adgn.llm.openai_utils.types import ReasoningSummary, to_reasoning_effort


async def _execute(
    *,
    file_path: Path,
    prompt: str,
    model: str,
    reasoning_effort: str | None,
    reasoning_summary: str | None,
    client: openai.AsyncOpenAI,
) -> int:
    # Validate input path
    target_path = file_path
    if not target_path.is_file():
        print(f"Error: {target_path} is not a file")
        return 2

    # Build in-proc MCP spec for the editor FastMCP server over memory streams
    spec = make_inproc_slot_spec(make_editor_mcp(target_path))
    slots = {"editor": spec}

    # Folded context: per-agent MCP lifetime + agent lifetime
    async with McpManager(slots) as mcp:
        # Normalize CLI strings to SDK-accepted values

        eff_str = to_reasoning_effort(reasoning_effort)
        effort_val: SDKReasoningEffort | None = None
        if eff_str is not None:
            effort_val = cast(SDKReasoningEffort, eff_str)
        summary_val = (
            None if reasoning_summary is None else ReasoningSummary(reasoning_summary)
        )

        # Create a per-run transcript directory (aligned with MiniCodex defaults)
        run_dir = Path.cwd() / "logs" / "mini_codex" / "llm_edit"
        run_dir = run_dir / f"run_{int(time.time())}_{os.getpid()}"
        run_dir.mkdir(parents=True, exist_ok=True)

        agent = await MiniCodex.create(
            model=model,
            mcp=mcp,
            system=(
                "You are a code editor assistant. Use tools to read/modify/save files.\n"
                "Operate on the provided file only. Prefer precise replace_text edits.\n"
                "Finish with done(success, report)."
            ),
            client=client,
            reasoning_effort=effort_val,
            reasoning_summary=summary_val,
            handlers=[
                AutoHandler(),
                DisplayEventsHandler(),
                TranscriptLoggerHandler(run_dir),
            ],
        )
        async with agent:
            res = await agent.run(
                f"Edit file: {target_path}\nGoal: {prompt}\n",
            )
            print(res.text)
            return 0


app = typer.Typer(help="LLM-powered single-file editor", add_completion=False)


def _run_cli(
    *,
    file_path: Path,
    prompt: str,
    model: str,
    reasoning_effort: str | None,
    reasoning_summary: str | None,
) -> None:
    # Construct a real AsyncOpenAI client only in the top-level CLI path and pass it explicitly
    client = openai.AsyncOpenAI()
    code = asyncio.run(
        _execute(
            file_path=file_path,
            prompt=prompt,
            model=model,
            reasoning_effort=reasoning_effort,
            reasoning_summary=reasoning_summary,
            client=client,
        ),
    )
    raise typer.Exit(code)


@app.command()
def edit(
    file_path: Path = typer.Argument(  # noqa: B008
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="Path to file to edit",
    ),
    prompt: str = typer.Argument(
        ...,
        help="Editing prompt",
    ),
    model: str = typer.Option(
        "o4-mini",
        "--model",
        help="Model name",
    ),
    reasoning_effort: str | None = typer.Option(
        None,
        help="Reasoning effort for reasoning-capable models (minimal/low/medium/high)",
    ),
    reasoning_summary: str | None = typer.Option(
        None,
        help="Emit reasoning summaries (auto/concise/detailed)",
    ),
) -> None:
    _run_cli(
        file_path=file_path,
        prompt=prompt,
        model=model,
        reasoning_effort=reasoning_effort,
        reasoning_summary=reasoning_summary,
    )


def main(argv: list[str] | None = None) -> None:
    # Typer entry; keep argv passthrough to avoid touching sys in tests
    if argv is None:
        app()
    else:
        app(argv=argv)


if __name__ == "__main__":
    main()

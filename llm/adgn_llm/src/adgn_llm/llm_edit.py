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
from pathlib import Path

import openai
import typer
from .openai_utils import ReasoningEffort, ReasoningSummary

from .mcp.editor_server import make_editor_mcp
from .mcp.inproc_utils import make_inproc_slot_spec
from .mini_codex.agent import MiniCodex
from .mini_codex.mcp_manager import McpManager




async def _execute(
    *,
    file_path: Path,
    prompt: str,
    model: str,
    reasoning_effort: ReasoningEffort | None,
    reasoning_summary: ReasoningSummary | None,
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
    async with (
        McpManager(slots) as mcp,
        await MiniCodex.create(
            model=model,
            mcp=mcp,
            system=(
                "You are a code editor assistant. Use tools to read/modify/save files.\n"
                "Operate on the provided file only. Prefer precise replace_text edits.\n"
                "Finish with done(success, report)."
            ),
            client=client,
            reasoning_effort=reasoning_effort,
            reasoning_summary=reasoning_summary,
        ) as agent,
    ):
        res = await agent.run(
            f"Edit file: {target_path}\nGoal: {prompt}\n",
            stream=False,
        )
        print(res.text)
        return 0


app = typer.Typer(help="LLM-powered single-file editor", add_completion=False)




def _run_cli(
    *,
    file_path: Path,
    prompt: str,
    model: str,
    reasoning_effort: ReasoningEffort | None,
    reasoning_summary: ReasoningSummary | None,
) -> None:
    client = openai.AsyncOpenAI()
    code = asyncio.run(
        _execute(
            file_path=file_path,
            prompt=prompt,
            model=model,
            reasoning_effort=reasoning_effort,
            reasoning_summary=reasoning_summary,
            client=client,
        )
    )
    raise typer.Exit(code)




@app.command()
def edit(
    file_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True, help="Path to file to edit"),
    prompt: str = typer.Argument(..., help="Editing prompt"),
    model: str = typer.Option("o4-mini", "--model", help="Model name"),
    reasoning_effort: ReasoningEffort | None = typer.Option(
        None,
        help="Reasoning effort for reasoning-capable models",
    ),
    reasoning_summary: ReasoningSummary | None = typer.Option(
        None,
        help="Emit reasoning summaries (omit to disable)",
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

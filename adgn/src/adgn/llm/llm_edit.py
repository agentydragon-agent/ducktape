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

from fastmcp.client import Client
import typer

from adgn.agent.agent import MiniCodex
from adgn.agent.event_renderer import DisplayEventsHandler
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
    reasoning_effort: str | None,
    reasoning_summary: str | None,
    client: OpenAIModelProto,
) -> int:
    # Validate input path
    target_path = file_path
    if not target_path.is_file():
        print(f"Error: {target_path} is not a file")
        return 2

    # Folded context: per-agent MCP lifetime + agent lifetime
    comp = Compositor("compositor")
    await comp.mount_inproc(EDITOR_SERVER_NAME, make_editor_server(target_path, name=EDITOR_SERVER_NAME))
    # Normalize CLI strings to adapter-level values (no direct SDK types)
    effort_val: ReasoningEffort | None = None
    if reasoning_effort is not None:
        try:
            effort_val = ReasoningEffort(reasoning_effort)
        except ValueError as exc:
            allowed = ", ".join(item.value for item in ReasoningEffort)
            raise ValueError(f"Invalid reasoning_effort={reasoning_effort!r}; expected one of: {allowed}") from exc
    summary_val = None if reasoning_summary is None else ReasoningSummary(reasoning_summary)

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
            reasoning_effort=effort_val,
            reasoning_summary=summary_val,
            handlers=[DisplayEventsHandler(), TranscriptHandler(events_path=run_dir / "events.jsonl")],
            tool_policy=RequireAnyTool(),
        )
        async with agent:
            res = await agent.run(f"Edit file: {target_path}\nGoal: {prompt}\n")
            print(res.text)
            return 0


app = typer.Typer(help="LLM-powered single-file editor", add_completion=False)


@app.command()
async def edit(
    file_path: Path = typer.Argument(  # noqa: B008
        ..., exists=True, dir_okay=False, readable=True, help="Path to file to edit"
    ),
    prompt: str = typer.Argument(..., help="Editing prompt"),
    model: str = typer.Option("o4-mini", "--model", help="Model name"),
    reasoning_effort: str | None = typer.Option(
        None, help="Reasoning effort for reasoning-capable models (minimal/low/medium/high)"
    ),
    reasoning_summary: str | None = typer.Option(None, help="Emit reasoning summaries (auto/concise/detailed)"),
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

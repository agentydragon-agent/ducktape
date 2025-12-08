"""CLI command to interrogate a stuck agent by loading its state from DB."""

from __future__ import annotations

from uuid import UUID

from fastmcp.client import Client as MCPClient
from rich.console import Console
from sqlalchemy import String, cast, select
import typer

from adgn.agent.agent import MiniCodex, TranscriptItem
from adgn.agent.display import DisplayEventsHandler
from adgn.agent.display.rich_display import CompactDisplayHandler
from adgn.agent.events import ApiRequest, AssistantText, ToolCall, ToolCallOutput, UserText
from adgn.agent.loop_control import ForbidAllTools
from adgn.cli_utils import async_run
from adgn.mcp.compositor.server import Compositor
from adgn.openai_utils.client_factory import build_client
from adgn.openai_utils.model import AssistantMessage, FunctionCallItem, ReasoningItem, UserMessage
from adgn.props.cli.common_options import OPT_MAX_LINES
from adgn.props.db import get_session, init_db
from adgn.props.db.models import Event


def _find_transcript_by_prefix(prefix: str) -> UUID:
    """Find transcript ID by prefix match.

    Args:
        prefix: Hex prefix of transcript ID

    Returns:
        Full UUID of matching transcript

    Raises:
        typer.BadParameter: If no match or multiple matches found
    """
    init_db()
    with get_session() as session:
        # Query events to find transcripts whose ID starts with the prefix
        # We'll use the transcript_id from Event table since there's no separate Transcript table
        stmt = (
            select(Event.transcript_id)
            .where(cast(Event.transcript_id, String).like(f"{prefix}%"))
            .group_by(Event.transcript_id)
        )
        results = session.execute(stmt).scalars().all()

        if not results:
            raise typer.BadParameter(f"No transcript found with prefix '{prefix}'")
        if len(results) > 1:
            ids = [str(t) for t in results]
            raise typer.BadParameter(f"Multiple transcripts match prefix '{prefix}': {ids}")

        return results[0]


@async_run
async def cmd_speak_with_dead(
    transcript_prefix: str,
    question: str,
    turn_index: int | None = typer.Option(
        None, "--turn-index", "-t", help="Truncate transcript at this turn index (0-based)"
    ),
    display: bool = typer.Option(
        True, "--display/--no-display", "-d", help="Display transcript before asking question"
    ),
    max_lines: int = OPT_MAX_LINES,
) -> None:
    """Interrogate a stuck agent by loading its state and asking a question.

    Args:
        transcript_prefix: Hex prefix of the transcript ID to load
        question: Question to ask the agent about why it's stuck
        turn_index: Optional turn index to truncate transcript at (useful for debugging specific points)
        display: Display transcript before asking question
        max_lines: Max lines per event in display

    Example:
        adgn-properties speak-with-dead 4a969972 'why are you stuck?'
        adgn-properties speak-with-dead 1e070b96 'what happened?' --turn-index 10
        adgn-properties speak-with-dead 7a2919d5 'Test' --display --max-lines 5
    """
    console = Console()

    console.print(f"[dim]Loading transcript {transcript_prefix}...[/dim]\n")

    # Find transcript by prefix
    transcript_id = _find_transcript_by_prefix(transcript_prefix)
    console.print(f"[dim]Found transcript: {transcript_id}[/dim]\n")

    init_db()

    # Load events from DB
    with get_session() as session:
        stmt = select(Event).where(Event.transcript_id == transcript_id).order_by(Event.sequence_num)
        events = session.execute(stmt).scalars().all()

        if not events:
            console.print(f"[yellow]No events found for transcript {transcript_id}[/yellow]")
            return

        console.print(f"[dim]Loaded {len(events)} events from transcript {transcript_id}[/dim]")

        # Extract model and system instructions from last ApiRequest event
        model: str | None = None
        system_instructions: str | None = None
        for event in reversed(events):
            if isinstance(event.payload, ApiRequest):
                model = event.payload.model
                system_instructions = event.payload.request.instructions
                break

        if model is None:
            console.print("[red]ERROR: No ApiRequest events found, cannot determine model[/red]")
            return

        console.print(f"[dim]Using model: {model}[/dim]")

        if system_instructions is None:
            console.print("[yellow]WARNING: No system instructions found in ApiRequest, using fallback prompt[/yellow]")
            system_instructions = (
                "You are reviewing your own execution trace. Answer the user's question about why you might be stuck."
            )
        else:
            console.print("[dim]Using system instructions from last ApiRequest event[/dim]")

        # Display transcript if requested (while still in session to access payload)
        if display:
            console.print(f"\n[cyan]{'=' * console.width}[/cyan]")
            console.print(f"[cyan]Displaying transcript (width={console.width}, max_lines={max_lines})[/cyan]")
            console.print(f"[cyan]{'=' * console.width}[/cyan]\n")

            # Create display console with terminal width
            display_console = Console(width=console.width)
            display_handler = CompactDisplayHandler(console=display_console, max_lines=max_lines, servers={})

            # Replay events through display handler
            for event in events:
                payload = event.payload

                if isinstance(payload, UserText):
                    display_handler.on_user_text_event(payload)
                elif isinstance(payload, AssistantText):
                    display_handler.on_assistant_text_event(payload)
                elif isinstance(payload, ToolCall):
                    display_handler.on_tool_call_event(payload)
                elif isinstance(payload, ToolCallOutput):
                    display_handler.on_tool_result_event(payload)
                elif isinstance(payload, ReasoningItem):
                    display_handler.on_reasoning(payload)

            console.print(f"\n[cyan]{'=' * console.width}[/cyan]")
            console.print("[cyan]End of transcript display[/cyan]")
            console.print(f"[cyan]{'=' * console.width}[/cyan]\n")

        # Reconstruct transcript from events (while still in session)
        transcript_items: list[TranscriptItem] = []
        for event in events:
            payload = event.payload

            if isinstance(payload, UserText):
                transcript_items.append(UserMessage.text(payload.text))
            elif isinstance(payload, AssistantText):
                transcript_items.append(AssistantMessage.text(payload.text))
            elif isinstance(payload, ToolCall):
                transcript_items.append(
                    FunctionCallItem(call_id=payload.call_id, name=payload.name, arguments=payload.args_json or "{}")
                )
            elif isinstance(payload, ToolCallOutput):
                transcript_items.append(payload)

    # Truncate transcript at turn_index if specified
    if turn_index is not None:
        if turn_index < 0 or turn_index >= len(transcript_items):
            console.print(
                f"[yellow]WARNING: turn_index {turn_index} out of range (0-{len(transcript_items) - 1}), "
                f"using full transcript[/yellow]"
            )
        else:
            transcript_items = transcript_items[: turn_index + 1]
            console.print(f"[dim]Truncated transcript at turn_index {turn_index}[/dim]")

    console.print(f"[dim]Reconstructed transcript with {len(transcript_items)} items[/dim]\n")

    # Create agent with loaded transcript
    client = build_client(model)

    # Create empty MCP compositor (no tools for interrogation)
    async with Compositor() as compositor, MCPClient(compositor) as mcp_client:
        agent = await MiniCodex.create(
            mcp_client=mcp_client,
            system=system_instructions,
            client=client,
            handlers=[DisplayEventsHandler()],
            parallel_tool_calls=False,
            tool_policy=ForbidAllTools(),  # Text-only response, no tool calls
        )

        # Set the reconstructed transcript
        agent._transcript = transcript_items

        # Run the agent with the question
        await agent.run(question)

"""CLI command to interrogate a stuck agent by loading its state from DB."""

from __future__ import annotations

import asyncio
from uuid import UUID

from fastmcp.client import Client as MCPClient
from rich.console import Console
from sqlalchemy import String, cast, select
import typer

from adgn.agent.agent import MiniCodex, TranscriptItem
from adgn.agent.display import DisplayEventsHandler
from adgn.agent.events import ApiRequest, AssistantText, ToolCall, ToolCallOutput, UserText
from adgn.agent.loop_control import ForbidAllTools
from adgn.mcp.compositor.server import Compositor
from adgn.openai_utils.client_factory import build_client
from adgn.openai_utils.model import AssistantMessage, FunctionCallItem, UserMessage
from adgn.props.db import get_session, init_db
from adgn.props.db.models import CriticRun, Event, GraderRun


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


async def _speak_with_dead_async(transcript_id: UUID, question: str) -> None:
    """Load agent state from DB and ask it a question.

    Args:
        transcript_id: Full UUID of the transcript
        question: Question to ask the agent
    """
    console = Console()
    init_db()

    # Load run metadata and events from DB
    with get_session() as session:
        # Try to find CriticRun first
        critic_run = session.execute(
            select(CriticRun).where(CriticRun.transcript_id == transcript_id)
        ).scalar_one_or_none()

        # If not found, try GraderRun
        grader_run = None
        if not critic_run:
            grader_run = session.execute(
                select(GraderRun).where(GraderRun.transcript_id == transcript_id)
            ).scalar_one_or_none()

        if not critic_run and not grader_run:
            console.print(f"[red]ERROR: No CriticRun or GraderRun found for transcript {transcript_id}[/red]")
            return

        # Extract model from run
        run = critic_run or grader_run
        assert run is not None, "Run should not be None after the check above"
        model = run.model
        console.print(f"[dim]Using model: {model}[/dim]")

        # Load events from DB
        stmt = select(Event).where(Event.transcript_id == transcript_id).order_by(Event.sequence_num)
        events = session.execute(stmt).scalars().all()

        if not events:
            console.print(f"[yellow]No events found for transcript {transcript_id}[/yellow]")
            return

        console.print(f"[dim]Loaded {len(events)} events from transcript {transcript_id}[/dim]")

        # Extract system instructions from last ApiRequest event
        system_instructions: str | None = None
        for event in reversed(events):
            if isinstance(event.payload, ApiRequest):
                system_instructions = event.payload.request.instructions
                break

        if system_instructions is None:
            console.print("[yellow]WARNING: No ApiRequest events found, using fallback interrogation prompt[/yellow]")
            system_instructions = (
                "You are reviewing your own execution trace. Answer the user's question about why you might be stuck."
            )
        else:
            console.print("[dim]Using system instructions from last ApiRequest event[/dim]")

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


def cmd_speak_with_dead(agent_type: str, transcript_prefix: str, question: str) -> None:
    """Interrogate a stuck agent by loading its state and asking a question.

    Args:
        agent_type: Type of agent (e.g., 'grader', 'critic') - currently informational only
        transcript_prefix: Hex prefix of the transcript ID to load
        question: Question to ask the agent about why it's stuck

    Example:
        adgn-properties speak-with-dead grader 4a969972 'why are you stuck?'
    """
    console = Console()
    console.print(f"[dim]Loading {agent_type} agent with transcript prefix {transcript_prefix}...[/dim]\n")

    # Find transcript by prefix
    transcript_id = _find_transcript_by_prefix(transcript_prefix)
    console.print(f"[dim]Found transcript: {transcript_id}[/dim]\n")

    # Run async interrogation
    asyncio.run(_speak_with_dead_async(transcript_id, question))

"""Example: Query execution traces to debug why a prompt succeeded or failed.

This script demonstrates how to link critic runs to prompts and examine
what tools were called during execution.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from rich.console import Console

from adgn.agent.events import ApiRequest, AssistantText, ReasoningItem, Response, ToolCall, ToolCallOutput, UserText
from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, Event, Prompt
from adgn.props.display import ColumnDef, build_table_from_schema, ellipticize, print_table_with_footer, short_sha


@dataclass
class CriticRunSummary:
    """Summary data for a critic run with enriched info."""

    run_id: UUID
    snapshot_slug: str
    prompt_sha256: str
    status: str
    tool_count: int


def format_event_detail(event: Event) -> tuple[str, str] | None:
    """Format event payload for display with truncation.

    Returns:
        (type, content) tuple for table display, or None to skip this event
    """
    payload = event.payload

    # Skip request/response events (big and not very useful)
    if isinstance(payload, (ApiRequest, Response)):
        return None

    if isinstance(payload, ToolCall):
        # Show tool name and args (truncated)
        args_str = ellipticize(str(payload.args_json) if payload.args_json else "{}", 100)
        return (event.event_type, f"{payload.name} | args: {args_str}")

    if isinstance(payload, ToolCallOutput):
        # Show first 50 chars of output, replacing newlines
        result = payload.result
        if result.isError:
            content = str(result.content) if result.content else "(no error message)"
        elif result.structuredContent:
            content = str(result.structuredContent)
        else:
            content = str(result.content) if result.content else ""
        content_clean = content.replace("\n", " ")
        content_ellipsized = ellipticize(content_clean, 50)
        status = "ERROR" if result.isError else "OK"
        return (f"{event.event_type} ({status})", content_ellipsized)

    if isinstance(payload, ReasoningItem):
        # Show first 100 chars of reasoning summary
        summary_text = " | ".join(item.text for item in payload.summary)
        return (event.event_type, ellipticize(summary_text, 100))

    if isinstance(payload, AssistantText):
        # Show first 100 chars of assistant text
        return (event.event_type, ellipticize(payload.text, 100))

    if isinstance(payload, UserText):
        # Show first 100 chars of user text
        return (event.event_type, ellipticize(payload.text, 100))

    # Fallback for other event types
    return (event.event_type, ellipticize(str(payload), 100))


def main():
    """Query execution traces for recent critic runs."""
    # One-time setup (reads PG* env vars)
    setup_agent_database()
    console = Console()

    with get_session() as session:
        # Get recent critic runs with their prompts
        recent_critics = (
            session.query(CriticRun, Prompt)
            .join(Prompt, CriticRun.prompt_sha256 == Prompt.prompt_sha256)
            .order_by(CriticRun.id.desc())
            .limit(5)
        )

        # Build enriched row data
        summaries: list[CriticRunSummary] = []
        for critic_run, prompt in recent_critics.all():
            status = critic_run.status

            # Count tool calls for this run
            tool_count = sum(1 for e in critic_run.events if e.event_type == "tool_call")

            summaries.append(
                CriticRunSummary(
                    run_id=critic_run.id,
                    snapshot_slug=critic_run.snapshot_slug,
                    prompt_sha256=prompt.prompt_sha256,
                    status=status,
                    tool_count=tool_count,
                )
            )

        console.print("\n[bold]Recent critic runs (last 5):[/bold]")

        columns: list[ColumnDef[Any, Any]] = [
            ColumnDef("Run ID", lambda r: str(r.run_id), short_sha, width=8),
            ColumnDef("Snapshot", lambda r: r.snapshot_slug, width=25),
            ColumnDef("Prompt", lambda r: r.prompt_sha256, short_sha, width=8),
            ColumnDef("Status", lambda r: r.status, width=15),
            ColumnDef("Tools", lambda r: r.tool_count, str, justify="right", width=6),
        ]

        console.print(build_table_from_schema(summaries, columns))

        # Show detailed execution trace for first run if available
        if summaries:
            first_run = summaries[0]
            console.print(f"\n[bold]Execution trace for run {short_sha(str(first_run.run_id))}:[/bold]")

            critic_run = (
                session.query(CriticRun).filter(CriticRun.id == first_run.run_id).first()
            )
            if critic_run and critic_run.events:
                console.print(f"Snapshot: {critic_run.snapshot_slug}")
                console.print(f"Prompt: {short_sha(critic_run.prompt_sha256)}...")
                console.print(f"Status: {first_run.status}")
                console.print(f"Tool calls: {first_run.tool_count}\n")

                # Show all events with details in table format (skip None results)
                formatted_events = [
                    (event_type, content)
                    for e in critic_run.events[:100]
                    if (detail := format_event_detail(e)) is not None
                    for event_type, content in [detail]
                ]
                event_rows = [(i, event_type, content) for i, (event_type, content) in enumerate(formatted_events, 1)]

                event_columns: list[ColumnDef[Any, Any]] = [
                    ColumnDef("#", lambda r: r[0], str, justify="right", width=3),
                    ColumnDef("Type", lambda r: r[1], width=12),
                    ColumnDef("Content", lambda r: r[2], width=80),
                ]
                print_table_with_footer(
                    console,
                    event_rows,
                    event_columns,
                    show_header=True,
                    total_count=len(critic_run.events),
                    item_name="events",
                )
            else:
                console.print("  No execution trace available")


def show_tool_sequence_for_transcript(transcript_id: UUID):
    """Show tool call sequence for a specific transcript.

    Usage:
        show_tool_sequence_for_transcript(UUID("..."))
    """
    setup_agent_database()
    console = Console()

    with get_session() as session:
        events = (
            session.query(Event)
            .filter(Event.transcript_id == transcript_id, Event.event_type == "tool_call")
            .order_by(Event.id)
            .all()
        )

        console.print(f"\n[bold]Tool sequence for transcript {str(transcript_id)[:8]}... ({len(events)} calls):[/bold]")

        # Build rows with sequence number and tool name
        # Payload is ToolCall since we filtered event_type == "tool_call"
        rows = [
            (i + 1, event.payload.name if isinstance(event.payload, ToolCall) else "unknown")
            for i, event in enumerate(events)
        ]

        columns: list[ColumnDef[Any, Any]] = [
            ColumnDef("#", lambda r: r[0], str, justify="right", width=4),
            ColumnDef("Tool", lambda r: r[1], width=50),
        ]

        console.print(build_table_from_schema(rows, columns))


if __name__ == "__main__":
    main()

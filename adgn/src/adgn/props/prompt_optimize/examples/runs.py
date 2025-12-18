"""Run status, execution traces, and failure analysis.

This module demonstrates how to query critic and grader run status, inspect
execution traces, and analyze failures for prompt improvement.

Functions:
- show_run_status(): Count runs by status (completed, max_turns_exceeded, etc.)
- show_execution_traces(): Show tool calls and events for recent runs
- analyze_critic_failure(): Deep-dive analysis of a specific critic run

These queries work with both optimization modes (whole-repo and targeted).
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from rich.console import Console
from sqlalchemy import func

from adgn.agent.events import ApiRequest, AssistantText, ReasoningItem, Response, ToolCall, ToolCallOutput, UserText
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, CriticRunStatus, Event, GraderRun, GraderRunStatus, GradingDecision, Prompt
from adgn.props.display import ColumnDef, build_table_from_schema, ellipticize, print_table_with_footer, short_sha


@dataclass
class CriticRunSummary:
    """Summary data for a critic run with enriched info."""

    run_id: UUID
    snapshot_slug: str
    prompt_sha256: str
    status: str
    tool_count: int


def _format_event_detail(event: Event) -> tuple[str, str] | None:
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


def show_run_status() -> None:
    """Query run status statistics.

    Shows count of critic and grader runs by status, and prompts with
    highest max_turns_exceeded rate (indicating potential issues).
    """
    console = Console()

    with get_session() as session:
        # Count critic runs by status
        console.print("\n[bold]Critic Run Status:[/bold]")
        critic_status_query = (
            session.query(CriticRun.status.label("status"), func.count(CriticRun.id).label("count"))
            .group_by(CriticRun.status)
        )
        critic_results = critic_status_query.all()

        columns: list[ColumnDef[Any, Any]] = [
            ColumnDef("Status", lambda r: r.status, width=30),
            ColumnDef("Count", lambda r: r.count, str, justify="right"),
        ]
        console.print(build_table_from_schema(critic_results, columns))

        # Count grader runs by status
        console.print("\n[bold]Grader Run Status:[/bold]")
        grader_status_query = (
            session.query(GraderRun.status.label("status"), func.count(GraderRun.id).label("count"))
            .group_by(GraderRun.status)
        )
        grader_results = grader_status_query.all()

        console.print(build_table_from_schema(grader_results, columns))

        # Show prompts with highest max_turns_exceeded rate
        console.print("\n[bold]Prompts with most max_turns_exceeded (top 5):[/bold]")
        max_turns_query = (
            session.query(
                CriticRun.prompt_sha256,
                func.count().filter(CriticRun.status == CriticRunStatus.MAX_TURNS_EXCEEDED).label("max_turns_count"),
                func.count().label("total_runs"),
            )
            .group_by(CriticRun.prompt_sha256)
            .order_by(func.count().filter(CriticRun.status == CriticRunStatus.MAX_TURNS_EXCEEDED).desc())
            .limit(5)
        )
        prompt_results = max_turns_query.all()

        prompt_columns: list[ColumnDef[Any, Any]] = [
            ColumnDef("Prompt", lambda r: r.prompt_sha256, short_sha, width=8),
            ColumnDef("Max Turns", lambda r: r.max_turns_count, str, justify="right"),
            ColumnDef("Total", lambda r: r.total_runs, str, justify="right"),
            ColumnDef(
                "Rate",
                lambda r: (r.max_turns_count / r.total_runs * 100) if r.total_runs > 0 else 0,
                lambda v: f"{v:.1f}%",
                justify="right",
            ),
        ]
        console.print(build_table_from_schema(prompt_results, prompt_columns))


def show_execution_traces(limit: int = 5) -> None:
    """Show execution traces for recent critic runs.

    Displays tool calls, commands, and results to understand what
    the critic did during execution.
    """
    console = Console()

    with get_session() as session:
        # Get recent critic runs with their prompts
        recent_critics = (
            session.query(CriticRun, Prompt)
            .join(Prompt, CriticRun.prompt_sha256 == Prompt.prompt_sha256)
            .order_by(CriticRun.id.desc())
            .limit(limit)
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

        console.print(f"\n[bold]Recent critic runs (last {limit}):[/bold]")

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
                    if (detail := _format_event_detail(e)) is not None
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


def show_tool_sequence_for_transcript(transcript_id: UUID) -> None:
    """Show tool call sequence for a specific transcript.

    Usage:
        show_tool_sequence_for_transcript(UUID("..."))
    """
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
        rows = [
            (i + 1, event.payload.name if isinstance(event.payload, ToolCall) else "unknown")
            for i, event in enumerate(events)
        ]

        columns: list[ColumnDef[Any, Any]] = [
            ColumnDef("#", lambda r: r[0], str, justify="right", width=4),
            ColumnDef("Tool", lambda r: r[1], width=50),
        ]

        console.print(build_table_from_schema(rows, columns))


def analyze_critic_failure(snapshot_slug: str, scope_hash: str) -> None:
    """Analyze critic failures on a specific training example.

    Shows:
    - Run status and completion info
    - Grader results (recall, missed issues)
    - Execution trace (tool calls, commands)

    Args:
        snapshot_slug: The snapshot to analyze
        scope_hash: The scope hash to analyze
    """
    console = Console()

    with get_session() as session:
        # Query critic runs for this specific example
        critic_runs = (
            session.query(CriticRun)
            .filter_by(snapshot_slug=snapshot_slug, scope_hash=scope_hash)
            .order_by(CriticRun.created_at.desc())
            .limit(5)
            .all()
        )

        if not critic_runs:
            print(f"No critic runs found for {snapshot_slug} / {short_sha(scope_hash)}...")
            return

        print(f"=== Found {len(critic_runs)} critic runs for example ===\n")
        print(f"Snapshot: {snapshot_slug}")
        print(f"Scope hash: {short_sha(scope_hash)}...")
        print()

        # Analyze the most recent run
        critic_run = critic_runs[0]
        print(f"Analyzing run: {critic_run.transcript_id}")
        print(f"Prompt: {short_sha(critic_run.prompt_sha256)}...")
        print(f"Model: {critic_run.model}")
        print()

        # Check run status
        print("=== Run Status ===\n")
        if critic_run.status != "completed":
            print(f"Status: {critic_run.status.upper()}")
            print("This run did NOT complete successfully. The critic may have:")
            print("- Run out of turns (hit max_turns limit)")
            print("- Exceeded context length (too many tokens)")
            print("- Encountered an error")
            print()
            return
        print("Status: COMPLETED")
        print(f"Critic Run ID: {critic_run.id}")
        print()

        # Get grader result for this critic run
        grader_run = session.query(GraderRun).filter_by(critic_run_id=critic_run.id).first()

        if not grader_run:
            print("No grader result found for this critic run (may not have been graded yet)")
            return

        # Show grader results
        print("=== Grader Results ===\n")
        if grader_run.status == GraderRunStatus.COMPLETED:
            # Query grading decisions directly
            total_credit = (
                session.query(func.sum(GradingDecision.credit))
                .filter_by(grader_run_id=grader_run.id)
                .filter(GradingDecision.target_tp_id.isnot(None))
                .scalar()
                or 0.0
            )

            n_occurrences = (
                session.query(GradingDecision.target_tp_id, GradingDecision.target_tp_occurrence_id)
                .filter_by(grader_run_id=grader_run.id)
                .filter(GradingDecision.target_tp_id.isnot(None))
                .distinct()
                .count()
            )

            print(f"Occurrences: {total_credit:.1f} / {n_occurrences} found")

            unique_tps = (
                session.query(GradingDecision.target_tp_id)
                .filter_by(grader_run_id=grader_run.id)
                .filter(GradingDecision.target_tp_id.isnot(None))
                .distinct()
                .count()
            )

            novel_count = (
                session.query(GradingDecision)
                .filter_by(grader_run_id=grader_run.id)
                .filter(GradingDecision.target_tp_id.is_(None))
                .count()
            )

            print(f"Unique TPs: {unique_tps}")
            print(f"Unknown Issues: {novel_count}")
            print()

            # Show missed issues (occurrences with zero found_credit)
            missed_decisions = (
                session.query(GradingDecision)
                .filter_by(grader_run_id=grader_run.id)
                .filter(GradingDecision.target_tp_id.isnot(None))
                .filter(GradingDecision.credit == 0.0)
                .limit(3)
                .all()
            )

            if missed_decisions:
                print(f"=== Missed Occurrences ({len(missed_decisions)} with zero credit shown) ===\n")
                for decision in missed_decisions:
                    print(f"  - {decision.target_tp_id} (occurrence {decision.target_tp_occurrence_id})")
                    if decision.input_issue_id:
                        print("    (Partially matched but zero credit)")
                    else:
                        print("    (Not matched at all)")
                    print()
        else:
            print(f"Grader run status: {grader_run.status.value}")
            print("Grader run did not complete successfully")
            return

        # Show execution trace
        console.print("\n[bold]=== Execution Trace (Events) ===[/bold]\n")

        formatted_events = [
            (event_type, content)
            for e in critic_run.events[:100]
            if (detail := _format_event_detail(e)) is not None
            for event_type, content in [detail]
        ]

        if formatted_events:
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


def main():
    """Run all run analysis examples."""
    show_run_status()
    print()
    show_execution_traces()


if __name__ == "__main__":
    main()

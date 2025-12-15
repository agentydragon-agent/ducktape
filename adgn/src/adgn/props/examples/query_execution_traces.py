"""Example: Query execution traces to debug why a prompt succeeded or failed.

This script demonstrates how to link critic runs to prompts and examine
what tools were called during execution.
"""

from uuid import UUID

from sqlalchemy import func

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, Event, GraderRun, Prompt
from adgn.props.db.snapshots import DBGraderSuccess


def main():
    """Query execution traces for recent critic runs."""
    # One-time setup (reads PG* env vars)
    setup_agent_database()

    with get_session() as session:
        # Get recent critic runs with their prompts
        print("Recent critic runs (last 5):")
        recent_critics = (
            session.query(CriticRun, Prompt)
            .join(Prompt, CriticRun.prompt_sha256 == Prompt.prompt_sha256)
            .order_by(CriticRun.id.desc())
            .limit(5)
        )

        for critic_run, prompt in recent_critics.all():
            status = critic_run.output.tag if critic_run.output else "unknown"
            print(f"\n  Critic Run {str(critic_run.id)[:8]}...")
            print(f"    Snapshot: {critic_run.snapshot_slug}")
            print(f"    Prompt: {prompt.prompt_sha256[:8]}...")
            print(f"    Status: {status}")

            # Count tool calls for this run
            tool_count = (
                session.query(func.count(Event.id))
                .filter(Event.transcript_id == critic_run.transcript_id, Event.event_type == "tool_call")
                .scalar()
            )
            print(f"    Tool calls: {tool_count}")

            # If this critic run has a grader run, show recall
            grader = (
                session.query(GraderRun)
                .filter(
                    GraderRun.critique_id == critic_run.critique_id,
                    GraderRun.output.isnot(None),  # type: ignore[arg-type]
                )
                .first()
            )
            if grader and grader.output and isinstance(grader.output, DBGraderSuccess):
                # Show absolute numbers instead of recall percentage
                if grader.output.occurrence_results:
                    total_credit = sum(o.found_credit for o in grader.output.occurrence_results)
                    n_occurrences = len(grader.output.occurrence_results)
                    print(f"    Occurrences: {total_credit:.1f} / {n_occurrences} found")
                else:
                    print("    Occurrences: 0 / 0 found")


def show_tool_sequence_for_transcript(transcript_id: UUID):
    """Show tool call sequence for a specific transcript.

    Usage:
        show_tool_sequence_for_transcript(UUID("..."))
    """
    setup_agent_database()

    with get_session() as session:
        events = (
            session.query(Event)
            .filter(Event.transcript_id == transcript_id, Event.event_type == "tool_call")
            .order_by(Event.id)
            .all()
        )

        print(f"Tool sequence for transcript {str(transcript_id)[:8]}... ({len(events)} calls):")
        for event in events:
            tool_name = event.payload.get("name", "unknown")
            print(f"  {tool_name}")


if __name__ == "__main__":
    main()

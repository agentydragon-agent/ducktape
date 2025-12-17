"""Example: Analyzing critic failures for prompt improvement.

This script demonstrates how to query critic runs, execution traces, and grader
results for YOUR ASSIGNED TRAINING EXAMPLES (scoped via RLS policies).

Key patterns:
- Query critic runs for your specific examples (by snapshot_slug, scope_hash)
- Access grader results (occurrence credits, false negatives)
- Inspect execution traces (tool calls, commands, results)
- Identify what the critic did vs what it should have done

Note: You only have access to the training examples assigned to you in the
improvement context. Query by (snapshot_slug, scope_hash) pairs.
"""

from typing import Any

from rich.console import Console

from sqlalchemy import func

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, GradingDecision, GraderRun, GraderRunStatus
from adgn.props.display import ColumnDef, print_table_with_footer, short_sha
from adgn.props.examples.query_execution_traces import format_event_detail

# Example keys (replace with your assigned examples from improvement context)
example_to_analyze = ("ducktape/2025-12-04-00", "2218c0dacb6594985f72b9c78880aea341de110ce28a1924054399aebc24da23")


def main():
    """Analyze critic failures on a specific training example."""
    setup_agent_database()
    console = Console()

    snapshot_slug, scope_hash = example_to_analyze

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
            # TODO: Deduplicate recall calculation into db/grading.py helper function

            # Total credit (recall numerator)
            total_credit = (
                session.query(func.sum(GradingDecision.credit))
                .filter_by(grader_run_id=grader_run.id)
                .filter(GradingDecision.target_tp_id.isnot(None))
                .scalar()
                or 0.0
            )

            # Occurrence count (recall denominator)
            n_occurrences = (
                session.query(GradingDecision.target_tp_id, GradingDecision.target_tp_occurrence_id)
                .filter_by(grader_run_id=grader_run.id)
                .filter(GradingDecision.target_tp_id.isnot(None))
                .distinct()
                .count()
            )

            print(f"Occurrences: {total_credit:.1f} / {n_occurrences} found")

            # Count unique TPs
            unique_tps = (
                session.query(GradingDecision.target_tp_id)
                .filter_by(grader_run_id=grader_run.id)
                .filter(GradingDecision.target_tp_id.isnot(None))
                .distinct()
                .count()
            )

            # Count unknowns (decisions with no TP match)
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

        # Format events using the same logic as query_execution_traces
        formatted_events = [
            (event_type, content)
            for e in critic_run.events[:100]
            if (detail := format_event_detail(e)) is not None
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


if __name__ == "__main__":
    main()

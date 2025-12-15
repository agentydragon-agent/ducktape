"""Example: Analyzing critic failures for prompt improvement.

This script demonstrates how to query critic runs, execution traces, and grader
results for YOUR ASSIGNED TRAINING EXAMPLES (scoped via RLS policies).

Key patterns:
- Query critic runs for your specific examples (by snapshot_slug, files_hash)
- Access grader results (recall, precision, false negatives)
- Inspect execution traces (tool calls, commands, results)
- Identify what the critic did vs what it should have done

Note: You only have access to the training examples assigned to you in the
improvement context. Query by (snapshot_slug, files_hash) pairs.
"""

from pydantic import TypeAdapter

from adgn.agent.events import ToolCall, ToolCallOutput
from adgn.mcp.exec.models import ExecInput
from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, Event, GraderRun
from adgn.props.db.snapshots import DBGraderSuccess

# Example keys (replace with your assigned examples from improvement context)
example_to_analyze = ("ducktape/2025-12-04-00", "2218c0dacb6594985f72b9c78880aea341de110ce28a1924054399aebc24da23")


def main():
    """Analyze critic failures on a specific training example."""
    setup_agent_database()

    snapshot_slug, files_hash = example_to_analyze

    with get_session() as session:
        # Query critic runs for this specific example
        critic_runs = (
            session.query(CriticRun)
            .filter_by(snapshot_slug=snapshot_slug, files_hash=files_hash)
            .order_by(CriticRun.created_at.desc())
            .limit(5)
            .all()
        )

        if not critic_runs:
            print(f"No critic runs found for {snapshot_slug} / {files_hash[:16]}...")
            return

        print(f"=== Found {len(critic_runs)} critic runs for example ===\n")
        print(f"Snapshot: {snapshot_slug}")
        print(f"Files hash: {files_hash[:16]}...")
        print()

        # Analyze the most recent run
        critic_run = critic_runs[0]
        print(f"Analyzing run: {critic_run.transcript_id}")
        print(f"Prompt: {critic_run.prompt_sha256[:12]}...")
        print(f"Model: {critic_run.model}")
        print()

        # Check run status
        print("=== Run Status ===\n")
        if critic_run.critique_id is None:
            print("Status: INCOMPLETE (no critique submitted)")
            print("Possible reasons: max turns exceeded, context length exceeded, error")
            print()
            print("This run did NOT complete successfully. The critic may have:")
            print("- Run out of turns (hit max_turns limit)")
            print("- Exceeded context length (too many tokens)")
            print("- Encountered an error")
            print()
            return
        print("Status: SUCCESS (critique submitted)")
        print(f"Critique ID: {critic_run.critique_id}")
        print()

        # Get grader result for this critic run
        grader_run = session.query(GraderRun).filter_by(critique_id=critic_run.critique_id).first()

        if not grader_run:
            print("No grader result found for this critic run (may not have been graded yet)")
            return

        # Show grader results
        print("=== Grader Results ===\n")
        if isinstance(grader_run.output, DBGraderSuccess):
            grade = grader_run.output
            # Print absolute numbers instead of percentage
            if grade.occurrence_results:
                total_credit = sum(o.found_credit for o in grade.occurrence_results)
                n_occurrences = len(grade.occurrence_results)
                print(f"Occurrences: {total_credit:.1f} / {n_occurrences} found")
            else:
                print("Occurrences: 0 / 0 found")

            # Count coverage entries
            tp_count = len(grade.canonical_tp_coverage)
            fp_count = len(grade.canonical_fp_coverage)
            novel_count = len(grade.novel_critique_issues)

            print(f"TP Coverage Entries: {tp_count}")
            print(f"FP Coverage Entries: {fp_count}")
            print(f"Novel Issues: {novel_count}")
            print()

            # Show missed issues (TPs with zero recall credit)
            missed = [entry for entry in grade.canonical_tp_coverage if entry.recall_credit == 0.0]
            if missed:
                print(f"=== Missed Issues ({len(missed)} TPs with zero recall credit) ===\n")
                for entry in missed[:3]:
                    print(f"  - {entry.canonical_id}")
                    if entry.matched_inputs:
                        print("    (Partially matched but zero credit)")
                    else:
                        print("    (Not matched at all)")
                    print()
        else:
            print("Grader run failed or incomplete")
            return

        # Show execution trace
        print("=== Execution Trace (Tool Calls) ===\n")
        events = (
            session.query(Event)
            .filter(Event.transcript_id == critic_run.transcript_id)
            .order_by(Event.sequence_num)
            .limit(10)
            .all()
        )

        if events:
            for evt in events:
                payload = evt.payload

                # Event payload is a typed Pydantic model (EventType discriminated union)
                # Access typed attributes instead of using .get()
                if isinstance(payload, ToolCall):
                    print(f"  [{evt.sequence_num}] CALL {payload.name}")

                    # Show interesting command args from docker_exec calls
                    if payload.args_json and "docker_exec" in payload.name:
                        # Use Pydantic TypeAdapter to parse docker_exec arguments
                        exec_input = TypeAdapter(ExecInput).validate_json(payload.args_json)
                        # Show truncated command
                        cmd_parts = exec_input.cmd[:5]
                        if len(exec_input.cmd) > 5:
                            cmd_parts.append("...")
                        print(f"       Command: {' '.join(cmd_parts)}")

                elif isinstance(payload, ToolCallOutput):
                    result = payload.result
                    if result.isError:
                        print(f"  [{evt.sequence_num}] ERROR")
                    else:
                        print(f"  [{evt.sequence_num}] OK")

            total_events = session.query(Event).filter(Event.transcript_id == critic_run.transcript_id).count()
            if len(events) < total_events:
                print(f"  ... ({total_events - len(events)} more events)")
        else:
            print("  No execution trace found")

        # Show reasoning summaries (if any)
        reasoning_events = (
            session.query(Event)
            .filter(Event.transcript_id == critic_run.transcript_id, Event.event_type == "reasoning")
            .order_by(Event.sequence_num)
            .all()
        )

        if reasoning_events:
            print("\n=== Reasoning Summaries ===\n")
            for evt in reasoning_events[:5]:  # Show first 5 reasoning events
                payload = evt.payload
                # Payload is a ReasoningItem with typed 'summary' attribute
                if hasattr(payload, "summary") and payload.summary:
                    print(f"  [{evt.sequence_num}] Reasoning:")
                    for item in payload.summary:
                        # Each item is a ReasoningSummaryItem with 'text' attribute
                        text = item.text if hasattr(item, "text") else str(item)
                        # Truncate long summaries
                        if len(text) > 100:
                            text = text[:100] + "..."
                        print(f"    - {text}")
                    print()

            if len(reasoning_events) > 5:
                print(f"  ... ({len(reasoning_events) - 5} more reasoning events)")


if __name__ == "__main__":
    main()

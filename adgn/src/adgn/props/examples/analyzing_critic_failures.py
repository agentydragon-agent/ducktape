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
        else:
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
            print(f"Recall: {grade.recall:.1%}")
            print(f"Precision: {grade.precision:.1%}")
            print(f"True Positives: {len(grade.true_positives)}")
            print(f"False Positives: {len(grade.false_positives)}")
            print(f"False Negatives: {len(grade.false_negatives)} (missed issues)")
            print()

            # Show some missed issues
            if grade.false_negatives:
                print("=== Sample Missed Issues (False Negatives) ===\n")
                for fn in grade.false_negatives[:3]:
                    print(f"  - {fn.canonical_id}")
                    print(f"    Category: {fn.category}")
                    print(f"    Rationale: {fn.rationale[:80]}...")
                    print()
        else:
            print("Grader run failed or incomplete")
            return

        # Show execution trace
        print("=== Execution Trace (Tool Calls) ===\n")
        events = (
            session.query(Event)
            .filter(Event.transcript_id == critic_run.transcript_id)
            .order_by(Event.sequence_number)
            .limit(10)
            .all()
        )

        if events:
            for evt in events:
                payload = evt.payload
                event_type = payload.get("type", "unknown")

                if event_type == "tool_call":
                    tool_name = payload.get("name", "unknown")
                    args = payload.get("arguments", {})
                    print(f"  [{evt.sequence_number}] CALL {tool_name}")

                    # Show interesting command args
                    if "command" in args:
                        cmd = args["command"]
                        if isinstance(cmd, list):
                            print(f"       Command: {' '.join(cmd[:5])}")
                        else:
                            print(f"       Command: {cmd[:60]}...")

                elif event_type == "tool_result":
                    print(f"  [{evt.sequence_number}] RESULT")
                    # Could show structured_content here if needed

            total_events = session.query(Event).filter(Event.transcript_id == critic_run.transcript_id).count()
            if len(events) < total_events:
                print(f"  ... ({total_events - len(events)} more events)")
        else:
            print("  No execution trace found")


if __name__ == "__main__":
    main()

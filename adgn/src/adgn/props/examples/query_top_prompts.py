"""Example: Query top-performing prompts on validation split.

This script demonstrates how to query the database to find which prompts
achieved the highest mean recall on validation examples.
"""

from sqlalchemy import select

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session
from adgn.props.db.models import AggregatedRecallByPrompt, Prompt
from adgn.props.splits import Split


def main():
    """Query and display top-performing prompts on validation split."""
    # One-time setup (reads PG* env vars)
    setup_agent_database()

    # Query the database
    with get_session() as session:
        # Get top-performing prompts on validation split
        # Query the aggregated_recall_by_prompt view (already computes mean recall per prompt)
        # Note: View groups by is_whole_snapshot, so same prompt may appear multiple times
        # (once for whole-snapshot, once for per-file aggregates)
        query = (
            select(
                AggregatedRecallByPrompt.prompt_sha256,
                AggregatedRecallByPrompt.recall,
                AggregatedRecallByPrompt.n_snapshots,
                AggregatedRecallByPrompt.n_occurrences,
            )
            .where(AggregatedRecallByPrompt.split == Split.VALID)
            .order_by(AggregatedRecallByPrompt.recall.desc())
            .limit(10)
        )

        top_prompts = session.execute(query).fetchall()

        print("Top 10 prompts on validation:")
        for sha, recall, n_snapshots, n_occurrences in top_prompts:
            # Get prompt text preview
            prompt = session.query(Prompt).filter_by(prompt_sha256=sha).first()
            preview = prompt.prompt_text[:100].replace("\n", " ") if prompt else "(not found)"
            snapshot_plural = "snapshots" if n_snapshots != 1 else "snapshot"
            occurrence_plural = "occurrences" if n_occurrences != 1 else "occurrence"
            recall_val = recall if recall is not None else 0.0
            print(
                f"  {sha[:8]}: {recall_val:.3f} ({n_snapshots} {snapshot_plural}, {n_occurrences} {occurrence_plural}) - {preview}..."
            )


if __name__ == "__main__":
    main()

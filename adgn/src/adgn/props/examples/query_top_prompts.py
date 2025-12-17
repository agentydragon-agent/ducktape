"""Example: Query top-performing prompts on validation split.

This script demonstrates how to query the database to find which prompts
achieved the highest mean recall on validation examples.
"""

from typing import Any

from rich.console import Console
from sqlalchemy import select

from adgn.props.agent_helpers import setup_agent_database
from adgn.props.db import get_session
from adgn.props.db.models import AggregatedRecallByPrompt, Prompt
from adgn.props.display import short_sha
from adgn.props.display import ColumnDef, build_table_from_schema
from adgn.props.splits import Split


def main():
    """Query and display top-performing prompts on validation split."""
    # One-time setup (reads PG* env vars)
    setup_agent_database()
    console = Console()

    # Query the database
    with get_session() as session:
        # Get top-performing prompts on validation split
        # Query uses occurrence-based weighting: occurrences caught / catchable occurrences
        # View computes recall with safe division (NULL if no catchable occurrences)
        query = (
            select(
                AggregatedRecallByPrompt.prompt_sha256,
                AggregatedRecallByPrompt.recall,
                AggregatedRecallByPrompt.avg_occurrences_caught_overall,
                AggregatedRecallByPrompt.avg_catchable_occurrences,
                AggregatedRecallByPrompt.total_catchable_occurrences,
                AggregatedRecallByPrompt.n_successful,
            )
            .where(AggregatedRecallByPrompt.split == Split.VALID)
            # Order by recall (pre-computed in view with safe division)
            .order_by(AggregatedRecallByPrompt.recall.desc().nulls_last())
            .limit(10)
        )

        top_prompts = session.execute(query).fetchall()

        # Enrich with prompt text previews
        rows_with_preview = []
        for row in top_prompts:
            prompt = session.query(Prompt).filter_by(prompt_sha256=row.prompt_sha256).first()
            preview = prompt.prompt_text[:100].replace("\n", " ") if prompt else "(not found)"
            rows_with_preview.append((row, preview))

        console.print("\n[bold]Top 10 prompts on validation (by occurrence-weighted recall):[/bold]")

        columns: list[ColumnDef[Any, Any]] = [
            ColumnDef("Prompt", lambda r: r[0].prompt_sha256, short_sha, width=8),
            ColumnDef("Recall", lambda r: r[0].recall,
                      lambda v: f"{v:.1%}" if v is not None else "-", justify="right"),
            ColumnDef("Caught", lambda r: r[0].avg_occurrences_caught_overall, lambda v: f"{v:.1f}", justify="right"),
            ColumnDef("Catchable", lambda r: r[0].total_catchable_occurrences, str, justify="right"),
            ColumnDef("Runs", lambda r: r[0].n_successful, str, justify="right"),
            ColumnDef("Preview", lambda r: r[1], width=40),
        ]

        console.print(build_table_from_schema(rows_with_preview, columns))


if __name__ == "__main__":
    main()

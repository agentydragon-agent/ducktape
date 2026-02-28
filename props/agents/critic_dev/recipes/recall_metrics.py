"""Recipe: Checking definition recall metrics.

Demonstrates how to query the recall leaderboard and per-example recall
breakdown using the materialized views and query_recall_by_example().
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from props.core.splits import Split
from props.db.models import RecallByDefinitionSplitKind
from props.db.query_builders import RecallByExampleRow, query_recall_by_example


def get_definition_leaderboard(session: Session, split: Split) -> list[RecallByDefinitionSplitKind]:
    """Query the recall leaderboard for a split, ordered by recall descending.

    Returns rows from the recall_by_definition_split_kind view which aggregates
    recall across all examples in the split.
    """
    rows = (
        session.query(RecallByDefinitionSplitKind)
        .filter(RecallByDefinitionSplitKind.split == split)
        .order_by(RecallByDefinitionSplitKind.recall_denominator.desc())
        .all()
    )
    # Sort by mean recall descending (rows without stats go last)
    return sorted(rows, key=lambda r: r.recall_stats.mean if r.recall_stats else -1.0, reverse=True)


def compare_definitions(session: Session, digest_a: str, digest_b: str, split: Split) -> str:
    """Compare two definitions' recall metrics side-by-side. Returns formatted string."""
    rows = (
        session.query(RecallByDefinitionSplitKind)
        .filter(
            RecallByDefinitionSplitKind.split == split,
            RecallByDefinitionSplitKind.critic_image_digest.in_([digest_a, digest_b]),
        )
        .all()
    )
    by_digest = {r.critic_image_digest: r for r in rows}

    lines = [f"Comparison on {split} split:", ""]
    for digest, label in [(digest_a, "A"), (digest_b, "B")]:
        r = by_digest.get(digest)
        if r is None:
            lines.append(f"  {label} ({digest[:16]}...): no data")
            continue
        recall_mean = f"{r.recall_stats.mean:.1%}" if r.recall_stats else "N/A"
        lines.append(
            f"  {label} ({digest[:16]}...): recall={recall_mean}, n_runs={r.n_runs}, n_examples={r.n_examples}"
        )

    return "\n".join(lines)


def get_per_example_recall(session: Session, critic_image_digest: str, split: Split) -> list[RecallByExampleRow]:
    """Get per-example recall breakdown for a specific definition."""
    return query_recall_by_example(session, split=split, critic_image_digest=critic_image_digest)

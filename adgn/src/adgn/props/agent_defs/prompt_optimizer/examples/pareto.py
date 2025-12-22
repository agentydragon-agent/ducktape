"""Pareto frontier analysis: which agent definitions win on which examples.

The pareto_frontier_by_example view identifies the best recall achieved on each
validation example and lists all agent definitions that achieved it.

Use cases:
- Find which definitions excel on specific examples
- Identify examples where no definition performs well (improvement opportunities)
- Understand definition specialization patterns
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Row

from adgn.props.db import get_session
from adgn.props.db.models import ParetoFrontierByExample
from adgn.props.display import short_sha
from adgn.props.splits import Split


def show_winning_prompts_orm(split: Split = Split.TRAIN, model: str = "gpt-5.1-codex-mini", limit: int = 10) -> None:
    """Find winning definitions using ORM."""
    with get_session() as session:
        pareto = (
            session.query(ParetoFrontierByExample)
            .filter(
                ParetoFrontierByExample.split == split,
                ParetoFrontierByExample.critic_model == model,
            )
            .order_by(ParetoFrontierByExample.best_recall.desc())
            .limit(limit)
            .all()
        )

        print(f"Top {limit} {split.value} examples by best recall:")
        for row in pareto:
            top_ids = ", ".join(short_sha(def_id) for def_id in row.winning_definition_ids[:3])
            print(f"  {row.snapshot_slug}/{short_sha(row.scope_hash)}: {row.best_recall:.2%} ({len(row.winning_definition_ids)} definitions, top: {top_ids})")


def show_prompts_by_wins_sql(model: str = "gpt-5.1-codex-mini", limit: int = 5) -> None:
    """Find definitions that win on multiple examples using raw SQL (unnest)."""
    with get_session() as session:
        result = session.execute(
            text("""
                SELECT
                    unnest(winning_definition_ids) as definition_id,
                    COUNT(*) as n_examples_won,
                    AVG(best_recall) as avg_best_recall
                FROM pareto_frontier_by_example
                WHERE split = 'valid' AND critic_model = :model
                GROUP BY definition_id
                ORDER BY n_examples_won DESC
                LIMIT :limit
            """),
            {"model": model, "limit": limit},
        )

        print(f"\nTop {limit} prompts by validation examples won:")
        sql_row: Row[Any]
        for sql_row in result:
            print(f"  {short_sha(sql_row.definition_id)}: {sql_row.n_examples_won} ex, {sql_row.avg_best_recall:.2%} avg")


def show_prompts_by_wins_orm(model: str = "gpt-5.1-codex-mini", limit: int = 5) -> None:
    """Same as above but using ORM + Python aggregation."""
    with get_session() as session:
        valid_pareto = (
            session.query(ParetoFrontierByExample)
            .filter(
                ParetoFrontierByExample.split == Split.VALID,
                ParetoFrontierByExample.critic_model == model,
            )
            .all()
        )

        # Count wins per definition using Python
        definition_stats: dict[str, list[float]] = {}
        for example in valid_pareto:
            for definition_id in example.winning_definition_ids:
                if definition_id not in definition_stats:
                    definition_stats[definition_id] = []
                definition_stats[definition_id].append(example.best_recall)

        top_definitions = sorted(definition_stats.items(), key=lambda x: len(x[1]), reverse=True)[:limit]
        print(f"\nTop {limit} definitions (ORM + Python):")
        for definition_id, recalls in top_definitions:
            print(f"  {short_sha(definition_id)}: {len(recalls)} ex, {sum(recalls)/len(recalls):.2%} avg")


def show_difficult_examples(split: Split = Split.TRAIN, model: str = "gpt-5.1-codex-mini", limit: int = 5) -> None:
    """Find examples with lowest best recall (improvement opportunities)."""
    with get_session() as session:
        difficult = (
            session.query(ParetoFrontierByExample)
            .filter(
                ParetoFrontierByExample.split == split,
                ParetoFrontierByExample.critic_model == model,
            )
            .order_by(ParetoFrontierByExample.best_recall.asc())
            .limit(limit)
            .all()
        )

        print(f"\n{limit} most difficult {split.value} examples:")
        for row in difficult:
            print(f"  {row.snapshot_slug}/{short_sha(row.scope_hash)}: {row.best_recall:.2%} ({len(row.winning_definition_ids)} definitions)")


def check_definition_wins(target_definition: str, model: str = "gpt-5.1-codex-mini") -> None:
    """Check if specific definition wins on validation examples."""
    with get_session() as session:
        valid_examples = (
            session.query(ParetoFrontierByExample)
            .filter(
                ParetoFrontierByExample.split == Split.VALID,
                ParetoFrontierByExample.critic_model == model,
            )
            .all()
        )

        wins = [ex for ex in valid_examples if target_definition in ex.winning_definition_ids]
        losses = [ex for ex in valid_examples if target_definition not in ex.winning_definition_ids]
        print(f"\nDefinition {short_sha(target_definition)}: {len(wins)}/{len(valid_examples)} wins", end="")
        if wins:
            print(f", avg {sum(ex.best_recall for ex in wins)/len(wins):.2%}", end="")
        if losses:
            print(f" | losses avg {sum(ex.best_recall for ex in losses)/len(losses):.2%}", end="")
        print()


def main():
    """Run pareto frontier examples."""
    show_winning_prompts_orm()
    show_prompts_by_wins_sql()
    show_prompts_by_wins_orm()
    show_difficult_examples()
    # Uncomment with actual definition ID to check specific definition:
    # check_definition_wins("abc123...")


if __name__ == "__main__":
    main()

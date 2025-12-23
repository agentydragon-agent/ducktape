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


def show_winning_definitions_orm(split: Split = Split.TRAIN, model: str | None = None, limit: int = 10) -> None:
    """Find winning critic definitions using ORM."""
    with get_session() as session:
        query = session.query(ParetoFrontierByExample).filter(ParetoFrontierByExample.split == split)
        if model is not None:
            query = query.filter(ParetoFrontierByExample.critic_model == model)
        pareto = query.order_by(ParetoFrontierByExample.best_mean_credit.desc()).limit(limit).all()

        model_suffix = f" (model: {model})" if model else ""
        print(f"Top {limit} {split.value} examples by best mean credit{model_suffix}:")
        for row in pareto:
            top_ids = ", ".join(short_sha(def_id) for def_id in row.winning_critic_definition_ids[:3])
            example_id = short_sha(row.files_hash) if row.files_hash else "whole"
            print(f"  {row.snapshot_slug}/{example_id}: {row.best_mean_credit:.2%} ({len(row.winning_critic_definition_ids)} definitions, top: {top_ids})")


def show_definitions_by_wins_sql(model: str | None = None, limit: int = 5) -> None:
    """Find critic definitions that win on multiple examples using raw SQL (unnest)."""
    with get_session() as session:
        model_filter = "AND critic_model = :model" if model else ""
        result = session.execute(
            text(f"""
                SELECT
                    unnest(winning_critic_definition_ids) as definition_id,
                    COUNT(*) as n_examples_won,
                    AVG(best_mean_credit) as avg_best_credit
                FROM pareto_frontier_by_example
                WHERE split = 'valid' {model_filter}
                GROUP BY definition_id
                ORDER BY n_examples_won DESC
                LIMIT :limit
            """),
            {"model": model, "limit": limit},
        )

        model_suffix = f" (model: {model})" if model else ""
        print(f"\nTop {limit} critic definitions by validation examples won{model_suffix}:")
        sql_row: Row[Any]
        for sql_row in result:
            print(f"  {short_sha(sql_row.definition_id)}: {sql_row.n_examples_won} ex, {sql_row.avg_best_credit:.2%} avg")


def show_definitions_by_wins_orm(model: str | None = None, limit: int = 5) -> None:
    """Find critic definitions that win on multiple examples using ORM + Python aggregation."""
    with get_session() as session:
        query = session.query(ParetoFrontierByExample).filter(ParetoFrontierByExample.split == Split.VALID)
        if model is not None:
            query = query.filter(ParetoFrontierByExample.critic_model == model)
        valid_pareto = query.all()

        # Count wins per definition using Python
        definition_stats: dict[str, list[float]] = {}
        for example in valid_pareto:
            for definition_id in example.winning_critic_definition_ids:
                if definition_id not in definition_stats:
                    definition_stats[definition_id] = []
                definition_stats[definition_id].append(example.best_mean_credit)

        top_definitions = sorted(definition_stats.items(), key=lambda x: len(x[1]), reverse=True)[:limit]
        print(f"\nTop {limit} definitions (ORM + Python):")
        for definition_id, recalls in top_definitions:
            print(f"  {short_sha(definition_id)}: {len(recalls)} ex, {sum(recalls)/len(recalls):.2%} avg")


def show_difficult_examples(split: Split = Split.TRAIN, model: str | None = None, limit: int = 5) -> None:
    """Find examples with lowest best recall (improvement opportunities)."""
    with get_session() as session:
        query = session.query(ParetoFrontierByExample).filter(ParetoFrontierByExample.split == split)
        if model is not None:
            query = query.filter(ParetoFrontierByExample.critic_model == model)
        difficult = query.order_by(ParetoFrontierByExample.best_mean_credit.asc()).limit(limit).all()

        model_suffix = f" (model: {model})" if model else ""
        print(f"\n{limit} most difficult {split.value} examples{model_suffix}:")
        for row in difficult:
            example_id = short_sha(row.files_hash) if row.files_hash else "whole"
            print(f"  {row.snapshot_slug}/{example_id}: {row.best_mean_credit:.2%} ({len(row.winning_critic_definition_ids)} definitions)")


def check_definition_wins(target_definition: str, model: str | None = None) -> None:
    """Check if specific definition wins on validation examples."""
    with get_session() as session:
        query = session.query(ParetoFrontierByExample).filter(ParetoFrontierByExample.split == Split.VALID)
        if model is not None:
            query = query.filter(ParetoFrontierByExample.critic_model == model)
        valid_examples = query.all()

        wins = [ex for ex in valid_examples if target_definition in ex.winning_critic_definition_ids]
        losses = [ex for ex in valid_examples if target_definition not in ex.winning_critic_definition_ids]
        print(f"\nDefinition {short_sha(target_definition)}: {len(wins)}/{len(valid_examples)} wins", end="")
        if wins:
            print(f", avg {sum(ex.best_mean_credit for ex in wins)/len(wins):.2%}", end="")
        if losses:
            print(f" | losses avg {sum(ex.best_mean_credit for ex in losses)/len(losses):.2%}", end="")
        print()


def main():
    """Run pareto frontier examples."""
    show_winning_definitions_orm()
    show_definitions_by_wins_sql()
    show_definitions_by_wins_orm()
    show_difficult_examples()
    # Uncomment with actual definition ID to check specific definition:
    # check_definition_wins("abc123...")


if __name__ == "__main__":
    main()

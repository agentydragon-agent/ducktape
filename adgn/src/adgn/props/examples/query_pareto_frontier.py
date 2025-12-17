"""Query Pareto frontier: which prompts win on which examples.

The pareto_frontier_by_example view identifies the best recall achieved on each
validation example and lists all prompts that achieved it.

Use cases:
- Find which prompts excel on specific examples
- Identify examples where no prompt performs well (opportunities for improvement)
- Understand prompt specialization patterns
"""

from collections import Counter
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.engine import Row

from adgn.props.db import get_session
from adgn.props.db.models import ParetoFrontierByExample
from adgn.props.db.examples import Example
from adgn.props.display import short_sha
from adgn.props.splits import Split

# Example 1: Find winning prompts for TRAIN split (using ORM)
with get_session() as session:
    train_pareto = (
        session.query(ParetoFrontierByExample)
        .filter(
            ParetoFrontierByExample.split == Split.TRAIN,
            ParetoFrontierByExample.critic_model == "gpt-5.1-codex-mini",
        )
        .order_by(ParetoFrontierByExample.best_recall.desc())
        .limit(10)
        .all()
    )

    print("Top 10 train examples by best recall:")
    for row in train_pareto:
        top_shas = ", ".join(short_sha(sha) for sha in row.winning_prompt_shas[:3])
        print(f"  {row.snapshot_slug}/{short_sha(row.scope_hash)}: {row.best_recall:.2%} ({len(row.winning_prompt_shas)} prompts, top: {top_shas})")

# Example 2: Find prompts that win on multiple examples (using SQL for unnest)
with get_session() as session:
    result = session.execute(
        text("""
            SELECT
                unnest(winning_prompt_shas) as prompt_sha256,
                COUNT(*) as n_examples_won,
                AVG(best_recall) as avg_best_recall
            FROM pareto_frontier_by_example
            WHERE split = 'valid' AND critic_model = 'gpt-5.1-codex-mini'
            GROUP BY prompt_sha256
            ORDER BY n_examples_won DESC
            LIMIT 5
        """)
    )

    print("\nTop 5 prompts by validation examples won:")
    sql_row: Row[Any]
    for sql_row in result:
        print(f"  {short_sha(sql_row.prompt_sha256)}: {sql_row.n_examples_won} ex, {sql_row.avg_best_recall:.2%} avg")

# Example 2b: Alternative using ORM + Python aggregation
with get_session() as session:
    valid_pareto = (
        session.query(ParetoFrontierByExample)
        .filter(
            ParetoFrontierByExample.split == Split.VALID,
            ParetoFrontierByExample.critic_model == "gpt-5.1-codex-mini",
        )
        .all()
    )

    # Count wins per prompt using Python
    prompt_stats: dict[str, list[float]] = {}
    for example in valid_pareto:
        for prompt_sha in example.winning_prompt_shas:
            if prompt_sha not in prompt_stats:
                prompt_stats[prompt_sha] = []
            prompt_stats[prompt_sha].append(example.best_recall)

    top_prompts = sorted(prompt_stats.items(), key=lambda x: len(x[1]), reverse=True)[:5]
    print("\nTop 5 prompts (ORM + Python):")
    for prompt_sha, recalls in top_prompts:
        print(f"  {short_sha(prompt_sha)}: {len(recalls)} ex, {sum(recalls)/len(recalls):.2%} avg")

# Example 3: Find difficult examples (low best recall) using ORM
with get_session() as session:
    difficult = (
        session.query(ParetoFrontierByExample)
        .filter(
            ParetoFrontierByExample.split == Split.TRAIN,
            ParetoFrontierByExample.critic_model == "gpt-5.1-codex-mini",
        )
        .order_by(ParetoFrontierByExample.best_recall.asc())
        .limit(5)
        .all()
    )

    print("\n5 most difficult train examples:")
    for row in difficult:
        print(f"  {row.snapshot_slug}/{short_sha(row.scope_hash)}: {row.best_recall:.2%} ({len(row.winning_prompt_shas)} prompts)")

# Example 4: Check if specific prompt wins on examples (using ORM)
with get_session() as session:
    target_prompt = "abc123..."  # Replace with actual SHA

    valid_examples = (
        session.query(ParetoFrontierByExample)
        .filter(
            ParetoFrontierByExample.split == Split.VALID,
            ParetoFrontierByExample.critic_model == "gpt-5.1-codex-mini",
        )
        .all()
    )

    wins = [ex for ex in valid_examples if target_prompt in ex.winning_prompt_shas]
    losses = [ex for ex in valid_examples if target_prompt not in ex.winning_prompt_shas]
    print(f"\nPrompt {short_sha(target_prompt)}: {len(wins)}/{len(valid_examples)} wins", end="")
    if wins:
        print(f", avg {sum(ex.best_recall for ex in wins)/len(wins):.2%}", end="")
    if losses:
        print(f" | losses avg {sum(ex.best_recall for ex in losses)/len(losses):.2%}", end="")
    print()

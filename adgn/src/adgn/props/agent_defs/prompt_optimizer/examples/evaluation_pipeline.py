"""Async evaluation pipeline using prompt optimizer helpers.

Demonstrates how to use run_critic and run_grader helpers for evaluation workflows.
The helpers wrap MCP tool calls with clean error handling and return typed results.

Workflow:
1. Create a critic definition from a directory (AGENT.md + init script)
2. Run critic on training examples using the definition
3. Grade each critique to compute metrics
4. Query database for aggregate results
"""

import asyncio

from adgn.props.db import get_session
from adgn.props.db.examples import Example
from helpers import create_critic_definition, run_critic, run_grader


async def evaluate_example(example: Example, definition_id: str) -> tuple[str, str, str]:
    """Run critic + grader on a single example, return IDs."""
    critic_output = await run_critic(
        definition_id=definition_id,
        snapshot_slug=example.snapshot_slug,
        scope_hash=example.scope_hash,
        max_turns=15,
    )

    grader_output = await run_grader(str(critic_output.critic_run_id), max_turns=200)

    return (
        f"{example.snapshot_slug}/{example.scope_hash[:8]}",
        str(critic_output.critic_run_id),
        str(grader_output.grader_run_id),
    )


async def main():
    """Evaluate a critic definition on training examples in parallel."""
    # 1. Create critic definition from directory
    # The directory must contain AGENT.md (system prompt) and init (bootstrap script)
    print("Creating critic definition...")
    definition_output = await create_critic_definition("/workspace/my_critic/")
    definition_id = definition_output.definition_id
    print(f"Created definition: {definition_id}")

    # 2. Query examples to evaluate
    with get_session() as session:
        train_examples = (
            session.query(Example).join(Example.snapshot_obj).filter(Example.snapshot_obj.has(split="train")).limit(5).all()
        )

    print(f"\nFound {len(train_examples)} training examples")

    # 3. Run critic+grader on all examples in parallel
    print("\nRunning evaluations in parallel...")
    tasks = [evaluate_example(example, definition_id) for example in train_examples]
    results = await asyncio.gather(*tasks)

    # 4. Print results
    print("\nEvaluation complete!")
    for example_id, critic_run_id, grader_run_id in results:
        print(f"  {example_id}: critic={critic_run_id}, grader={grader_run_id}")

    # 5. Query aggregate metrics from database
    print("\nTo query metrics, use:")
    print(f"""
from sqlalchemy import text
from adgn.props.db import get_session

with get_session() as session:
    result = session.execute(text('''
        SELECT recall, n_examples, ucb, lcb
        FROM aggregated_recall_by_definition
        WHERE agent_definition_id = :def_id AND split = 'train'
    '''), {{"def_id": "{definition_id}"}})
    for row in result:
        print(row)
""")


if __name__ == "__main__":
    asyncio.run(main())

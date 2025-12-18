"""Async evaluation pipeline using prompt optimizer helpers.

Demonstrates how to use run_critic and run_grader helpers for evaluation workflows.
The helpers wrap MCP tool calls with clean error handling and return typed results.
"""

import asyncio

from adgn.props.db import get_session
from adgn.props.db.examples import Example
from adgn.props.prompt_optimize.helpers import run_critic, run_grader, upsert_prompt


async def evaluate_example(example: Example, prompt_sha256: str) -> tuple[str, str, str]:
    """Run critic + grader on a single example, return IDs."""
    critic_output = await run_critic(
        snapshot_slug=example.snapshot_slug,
        scope_hash=example.scope_hash,
        prompt_sha256=prompt_sha256,
        max_turns=15,
    )

    grader_output = await run_grader(str(critic_output.critic_run_id), max_turns=200)

    return (
        f"{example.snapshot_slug}/{example.scope_hash[:8]}",
        str(critic_output.critic_run_id),
        str(grader_output.grader_run_id),
    )


async def main():
    """Evaluate a prompt on training examples in parallel."""
    # 1. Upsert prompt from file
    print("Upserting prompt...")
    upsert_output = await upsert_prompt("/workspace/my_prompt.txt")
    print(f"Prompt SHA256: {upsert_output.prompt_sha256}")

    # 2. Query examples to evaluate
    with get_session() as session:
        train_examples = (
            session.query(Example).join(Example.snapshot_obj).filter(Example.snapshot_obj.has(split="train")).limit(5).all()
        )

    print(f"\nFound {len(train_examples)} training examples")

    # 3. Run critic+grader on all examples in parallel
    print("\nRunning evaluations in parallel...")
    tasks = [evaluate_example(example, upsert_output.prompt_sha256) for example in train_examples]
    results = await asyncio.gather(*tasks)

    # 4. Print results
    print("\nEvaluation complete!")
    for example_id, critic_run_id, grader_run_id in results:
        print(f"  {example_id}: critic={critic_run_id}, grader={grader_run_id}")


if __name__ == "__main__":
    asyncio.run(main())

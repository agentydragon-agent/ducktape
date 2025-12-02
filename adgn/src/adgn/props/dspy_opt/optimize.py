"""Main optimization loop for critic prompt optimization.

This module ties everything together:
1. Load specimens as examples (train/valid split)
2. Create ReAct critic with workspace tools
3. Run DSPy teleprompter to optimize the prompt
4. Evaluate on validation set with full LLM grader
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import dspy
from dspy.teleprompt import BootstrapFewShot

if TYPE_CHECKING:
    from adgn.props.specimens.registry import SpecimenRegistry

from adgn.props.dspy_opt.examples import (
    SpecimenExample,
    load_specimens_as_examples,
    split_examples,
)
from adgn.props.dspy_opt.metric import (
    GraderMetricWithContext,
    simple_recall_metric,
)
from adgn.props.dspy_opt.signature import FindCodeIssues
from adgn.props.dspy_opt.tools import WorkspaceTools, workspace_context
from adgn.props.splits import Split

logger = logging.getLogger(__name__)


@dataclass
class OptimizationResult:
    """Result of prompt optimization."""

    optimized_module: dspy.Module
    train_scores: list[float]
    valid_scores: list[float]
    train_avg: float
    valid_avg: float


async def run_critic_on_example(
    critic: dspy.Module,
    example: SpecimenExample,
    registry: "SpecimenRegistry",
) -> dspy.Prediction:
    """Run critic on a single example with workspace context.

    Args:
        critic: DSPy ReAct critic module
        example: SpecimenExample to evaluate
        registry: SpecimenRegistry for hydrating specimen

    Returns:
        DSPy Prediction with issues found
    """
    async with registry.load_and_hydrate(example.slug) as hydrated:
        async with workspace_context(hydrated):
            # Run the critic - DSPy handles the ReAct loop
            prediction = critic(
                specimen_slug=example.slug,
                target_files=example.target_files,
            )
            return prediction


async def evaluate_on_examples(
    critic: dspy.Module,
    examples: list[SpecimenExample],
    registry: "SpecimenRegistry",
    *,
    use_full_grader: bool = False,
    verbose: bool = False,
) -> list[float]:
    """Evaluate critic on a list of examples.

    Args:
        critic: DSPy ReAct critic module
        examples: List of SpecimenExample to evaluate
        registry: SpecimenRegistry for hydrating specimens
        use_full_grader: Use LLM grader (slow) vs simple metric (fast)
        verbose: Enable verbose logging

    Returns:
        List of scores (one per example)
    """
    scores = []

    for example in examples:
        logger.info(f"Evaluating on {example.slug}...")

        async with registry.load_and_hydrate(example.slug) as hydrated:
            async with workspace_context(hydrated):
                # Run critic
                prediction = critic(
                    specimen_slug=example.slug,
                    target_files=example.target_files,
                )

                # Score
                if use_full_grader:
                    metric = GraderMetricWithContext(example, hydrated)
                    score = await metric.evaluate(prediction)
                    if verbose and metric.last_output:
                        logger.info(f"  Grader output: recall={score:.2%}")
                else:
                    score = simple_recall_metric(example, prediction)

                scores.append(score)
                logger.info(f"  Score: {score:.2%}")

    return scores


def create_critic_module() -> dspy.Module:
    """Create the critic module (ReAct with workspace tools).

    Returns:
        DSPy ReAct module configured for code review
    """
    return dspy.ReAct(
        FindCodeIssues,
        tools=WorkspaceTools.as_list(),
        max_iters=10,  # Limit iterations
    )


async def optimize_critic(
    registry: "SpecimenRegistry",
    *,
    max_bootstrapped_demos: int = 4,
    max_labeled_demos: int = 4,
    num_threads: int = 1,  # DSPy parallelism (separate from workspace context)
    verbose: bool = False,
) -> OptimizationResult:
    """Optimize critic prompt using DSPy teleprompter.

    Args:
        registry: SpecimenRegistry with specimens
        max_bootstrapped_demos: Max examples to bootstrap from
        max_labeled_demos: Max labeled demos in prompt
        num_threads: DSPy parallelism
        verbose: Enable verbose logging

    Returns:
        OptimizationResult with optimized module and scores
    """
    # Load all specimens and split
    logger.info("Loading specimens...")
    all_examples = await load_specimens_as_examples(registry)
    train_examples, valid_examples, _test_examples = split_examples(all_examples)

    logger.info(f"Loaded {len(train_examples)} train, {len(valid_examples)} valid examples")

    if not train_examples:
        raise ValueError("No training examples found")

    # Create base critic
    base_critic = create_critic_module()

    # Create metric function for teleprompter
    # Note: DSPy teleprompter calls this synchronously, so we use simple metric
    # The full grader is used in final evaluation
    def metric_fn(example_dict: dict, prediction: dspy.Prediction, trace=None) -> float:
        # Reconstruct SpecimenExample from dict (DSPy passes dict internally)
        # Find matching example by slug
        slug = example_dict.get("specimen_slug", "")
        matching = [ex for ex in train_examples if ex.slug == slug]
        if not matching:
            logger.warning(f"No matching example for slug {slug}")
            return 0.0
        return simple_recall_metric(matching[0], prediction, trace)

    # Run teleprompter
    logger.info("Running BootstrapFewShot optimization...")
    teleprompter = BootstrapFewShot(
        metric=metric_fn,
        max_bootstrapped_demos=max_bootstrapped_demos,
        max_labeled_demos=max_labeled_demos,
    )

    # DSPy expects examples as dspy.Example objects
    train_dspy = [ex.dspy_example for ex in train_examples]

    # Compile (this runs the optimization)
    # Note: DSPy's compile is synchronous, but our tools need async context
    # This is a limitation - we may need to run tools in a sync wrapper
    optimized_critic = teleprompter.compile(
        base_critic,
        trainset=train_dspy,
    )

    logger.info("Optimization complete. Evaluating...")

    # Evaluate on train and valid
    train_scores = await evaluate_on_examples(
        optimized_critic,
        train_examples,
        registry,
        use_full_grader=False,
        verbose=verbose,
    )

    valid_scores = await evaluate_on_examples(
        optimized_critic,
        valid_examples,
        registry,
        use_full_grader=True,  # Use full grader on validation
        verbose=verbose,
    )

    train_avg = sum(train_scores) / len(train_scores) if train_scores else 0.0
    valid_avg = sum(valid_scores) / len(valid_scores) if valid_scores else 0.0

    logger.info(f"Train avg: {train_avg:.2%}, Valid avg: {valid_avg:.2%}")

    return OptimizationResult(
        optimized_module=optimized_critic,
        train_scores=train_scores,
        valid_scores=valid_scores,
        train_avg=train_avg,
        valid_avg=valid_avg,
    )


def save_optimized_prompt(module: dspy.Module, path: Path) -> None:
    """Save optimized module state to file.

    Args:
        module: Optimized DSPy module
        path: Output path (JSON)
    """
    import json

    state = module.dump_state()
    path.write_text(json.dumps(state, indent=2))
    logger.info(f"Saved optimized prompt to {path}")


def load_optimized_prompt(path: Path) -> dspy.Module:
    """Load optimized module state from file.

    Args:
        path: Path to saved state (JSON)

    Returns:
        DSPy module with loaded state
    """
    import json

    state = json.loads(path.read_text())
    module = create_critic_module()
    module.load_state(state)
    return module

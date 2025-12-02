"""Prompt optimization using DSPy for instruction generation, existing infrastructure for execution.

DSPy is used ONLY for generating/optimizing prompt text.
Agent execution uses existing run_critic() and grade_critique_by_id().

The loop:
1. Start with initial prompt
2. Run critic on train specimens (via run_critic)
3. Grade each (via grade_critique_by_id)
4. Use DSPy LM to propose improved prompt based on failures
5. Repeat until convergence or budget exhausted
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

import dspy

if TYPE_CHECKING:
    from adgn.openai_utils.model import OpenAIModelProto
    from adgn.props.critic import CriticInput, CriticSuccess
    from adgn.props.grader import GraderOutput
    from adgn.props.specimens.registry import SpecimenRegistry

from adgn.props.splits import Split

logger = logging.getLogger(__name__)


@dataclass
class EvalResult:
    """Result of evaluating a prompt on one specimen."""

    specimen_slug: str
    critic_run_id: UUID
    critique_id: UUID
    grader_run_id: UUID
    recall: float
    grader_summary: str


@dataclass
class PromptEvaluation:
    """Full evaluation of a prompt on a set of specimens."""

    prompt_sha256: str
    results: list[EvalResult]

    @property
    def avg_recall(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.recall for r in self.results) / len(self.results)

    @property
    def failures(self) -> list[EvalResult]:
        """Results with recall < 1.0."""
        return [r for r in self.results if r.recall < 1.0]


async def evaluate_prompt_on_specimens(
    prompt_sha256: str,
    specimen_slugs: list[str],
    registry: "SpecimenRegistry",
    client: "OpenAIModelProto",
    *,
    verbose: bool = False,
) -> PromptEvaluation:
    """Evaluate a prompt on specimens using existing critic + grader.

    Args:
        prompt_sha256: SHA256 of prompt to evaluate (must exist in DB)
        specimen_slugs: Specimens to evaluate on
        registry: SpecimenRegistry instance
        client: LLM client for critic/grader
        verbose: Enable verbose logging

    Returns:
        PromptEvaluation with results for each specimen
    """
    from adgn.props.critic import ALL_FILES_WITH_ISSUES, CriticInput, run_critic
    from adgn.props.grader import grade_critique_by_id

    results = []

    for slug in specimen_slugs:
        logger.info(f"Evaluating on {slug}...")

        # Run critic
        async with registry.load_and_hydrate(slug) as hydrated:
            critic_input = CriticInput(
                specimen_slug=slug,
                files=ALL_FILES_WITH_ISSUES,
                prompt_sha256=prompt_sha256,
            )

            critic_output, critic_run_id, critique_id = await run_critic(
                input_data=critic_input,
                client=client,
                content_root=hydrated.content_root,
                registry=registry,
                mount_properties=True,
                verbose=verbose,
            )

        # Grade
        grader_run_id = await grade_critique_by_id(critique_id, client, verbose=verbose)

        # Fetch grader output for metrics
        from adgn.props.db import get_session
        from adgn.props.db.models import GraderRun as DBGraderRun
        from adgn.props.grader import GraderOutput

        with get_session() as session:
            grader_run = session.get(DBGraderRun, grader_run_id)
            grader_output = GraderOutput.model_validate(grader_run.output)

        recall = grader_output.recall
        summary = grader_output.grade.summary

        logger.info(f"  {slug}: recall={recall:.2%}")

        results.append(
            EvalResult(
                specimen_slug=slug,
                critic_run_id=critic_run_id,
                critique_id=critique_id,
                grader_run_id=grader_run_id,
                recall=recall,
                grader_summary=summary,
            )
        )

    return PromptEvaluation(prompt_sha256=prompt_sha256, results=results)


class PromptImprover(dspy.Signature):
    """Improve a code review prompt based on evaluation failures.

    Given the current prompt and feedback about what it missed, propose
    an improved version that would catch those issues.
    """

    current_prompt: str = dspy.InputField(desc="Current system prompt for code reviewer")
    failures: str = dspy.InputField(
        desc="Description of what the reviewer missed: specimen slugs, "
        "missed issues, grader feedback"
    )
    avg_recall: float = dspy.InputField(desc="Current average recall (0-1)")

    improved_prompt: str = dspy.OutputField(
        desc="Improved system prompt. Keep the same structure but add/refine "
        "instructions to catch the missed issues. Be specific about patterns."
    )
    changes_made: str = dspy.OutputField(desc="Brief summary of what you changed and why")


def format_failures_for_improver(evaluation: PromptEvaluation) -> str:
    """Format evaluation failures for the prompt improver."""
    if not evaluation.failures:
        return "No failures - perfect recall on all specimens."

    lines = []
    for r in evaluation.failures:
        lines.append(f"## {r.specimen_slug} (recall={r.recall:.2%})")
        lines.append(f"Grader feedback: {r.grader_summary}")
        lines.append("")

    return "\n".join(lines)


async def improve_prompt(
    current_prompt: str,
    evaluation: PromptEvaluation,
) -> tuple[str, str]:
    """Use DSPy LM to propose an improved prompt.

    Args:
        current_prompt: Current system prompt text
        evaluation: Evaluation results with failures

    Returns:
        (improved_prompt, changes_summary) tuple
    """
    improver = dspy.ChainOfThought(PromptImprover)

    result = improver(
        current_prompt=current_prompt,
        failures=format_failures_for_improver(evaluation),
        avg_recall=evaluation.avg_recall,
    )

    return result.improved_prompt, result.changes_made


async def optimize_critic_prompt(
    initial_prompt: str,
    registry: "SpecimenRegistry",
    client: "OpenAIModelProto",
    *,
    max_iterations: int = 5,
    target_recall: float = 0.95,
    verbose: bool = False,
) -> tuple[str, list[PromptEvaluation]]:
    """Optimize critic prompt using train specimens.

    Args:
        initial_prompt: Starting system prompt
        registry: SpecimenRegistry instance
        client: LLM client
        max_iterations: Max optimization iterations
        target_recall: Stop if avg recall exceeds this
        verbose: Enable verbose logging

    Returns:
        (best_prompt, evaluation_history) tuple
    """
    from adgn.props.db.prompts import hash_and_upsert_prompt

    # Get train specimens
    train_slugs = registry.get_specimens_by_split(Split.TRAIN)
    if not train_slugs:
        raise ValueError("No training specimens found")

    logger.info(f"Optimizing on {len(train_slugs)} train specimens")

    current_prompt = initial_prompt
    history: list[PromptEvaluation] = []
    best_prompt = initial_prompt
    best_recall = 0.0

    for iteration in range(max_iterations):
        logger.info(f"\n=== Iteration {iteration + 1}/{max_iterations} ===")

        # Store prompt in DB and get SHA
        prompt_sha256 = hash_and_upsert_prompt(current_prompt)

        # Evaluate current prompt
        evaluation = await evaluate_prompt_on_specimens(
            prompt_sha256=prompt_sha256,
            specimen_slugs=train_slugs,
            registry=registry,
            client=client,
            verbose=verbose,
        )
        history.append(evaluation)

        logger.info(f"Avg recall: {evaluation.avg_recall:.2%}")

        # Track best
        if evaluation.avg_recall > best_recall:
            best_recall = evaluation.avg_recall
            best_prompt = current_prompt

        # Check convergence
        if evaluation.avg_recall >= target_recall:
            logger.info(f"Target recall {target_recall:.2%} achieved!")
            break

        if not evaluation.failures:
            logger.info("No failures to improve on")
            break

        # Generate improved prompt
        logger.info("Generating improved prompt...")
        current_prompt, changes = await improve_prompt(current_prompt, evaluation)
        logger.info(f"Changes: {changes}")

    return best_prompt, history


async def evaluate_on_validation(
    prompt: str,
    registry: "SpecimenRegistry",
    client: "OpenAIModelProto",
    *,
    verbose: bool = False,
) -> PromptEvaluation:
    """Evaluate optimized prompt on validation set.

    Args:
        prompt: Optimized system prompt
        registry: SpecimenRegistry instance
        client: LLM client
        verbose: Enable verbose logging

    Returns:
        PromptEvaluation on validation specimens
    """
    from adgn.props.db.prompts import hash_and_upsert_prompt

    valid_slugs = registry.get_specimens_by_split(Split.VALID)
    if not valid_slugs:
        raise ValueError("No validation specimens found")

    prompt_sha256 = hash_and_upsert_prompt(prompt)

    return await evaluate_prompt_on_specimens(
        prompt_sha256=prompt_sha256,
        specimen_slugs=valid_slugs,
        registry=registry,
        client=client,
        verbose=verbose,
    )

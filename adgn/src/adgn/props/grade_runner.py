from __future__ import annotations

from pathlib import Path
from typing import Any

from adgn.agent.handler import BaseHandler
from adgn.openai_utils.model import OpenAIModelProto
from adgn.props.agent_runners import run_grader_agent
from adgn.props.critic import CriticSubmitPayload
from adgn.props.grader import GradeSubmitInput
from adgn.props.specimens.registry import SpecimenRegistry


def _metrics_row(grade: GradeSubmitInput, *, specimen: str | None = None) -> dict[str, Any]:
    """Extract metrics row from GradeSubmitInput."""
    # Use reported_issue_ratios and recall from the model
    row: dict[str, Any] = {**grade.reported_issue_ratios.model_dump(), "recall": grade.recall}
    if specimen is not None:
        row["specimen"] = specimen
    return row


async def grade_critic_output(
    specimen: str,
    critic_obj: CriticSubmitPayload,
    client: OpenAIModelProto,
    *,
    transcript_out_dir: Path,
    extra_handlers: tuple[BaseHandler, ...] = (),
    verbose: bool = False,
    verbose_prefix: str = "",
):
    """Grade a critic output JSON for a specimen; return GradeSubmitInput model.

    - Loads canonical positives and known false positives from SpecimenRegistry
    - Builds a grading prompt and runs MiniCodex with an in-proc grader_submit server
    - If transcript_out_dir is provided, writes JSONL transcript under transcript_out_dir/"grader"

    Args:
        specimen: Specimen slug
        critic_obj: Critique payload to grade
        client: OpenAI-compatible client
        transcript_out_dir: Directory for transcript and unknowns
        extra_handlers: Additional handlers (e.g., CostTrackingHandler) - excludes RichDisplayHandler
        verbose: If True, create RichDisplayHandler with proper server wiring
        verbose_prefix: Prefix for RichDisplayHandler output
    """
    # Load and hydrate specimen (single hydration, avoid wasteful re-hydrate)
    async with SpecimenRegistry.load_and_hydrate(specimen) as (rec, content_root):
        # Use shared grader runner
        return await run_grader_agent(
            specimen_rec=rec,
            content_root=content_root,
            critique=critic_obj,
            canonical_issues=None,  # Use all specimen issues
            known_fps=None,  # Use all specimen FPs
            scope_text=f"Specimen: {specimen}",
            client=client,
            transcript_dir=transcript_out_dir / "grader",
            extra_handlers=extra_handlers,
            verbose=verbose,
            verbose_prefix=verbose_prefix,
        )

"""Run models for properties evaluation (critic/grader/orchestrated evals).

Defines type-safe scope models (specimen vs file), input/output models for atomic runs
(CriticRun, GraderRun), and orchestrated eval sessions (FullSplitEval).

All models preserve the rich type safety from critic.py and grader.py:
- Typed namespaced IDs (TruePositiveID, FalsePositiveID, InputIssueID)
- Detailed coverage models (CanonicalTPCoverage, CanonicalFPCoverage)
- Validation contexts and metrics

Path computation is done via scope.scope_id() - NEVER parse paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from adgn.props.critic import CriticErrorPayload, CriticSubmitPayload
from adgn.props.grader import GradeSubmitInput
from adgn.props.ids import SpecimenSlug
from adgn.props.splits import Split, get_split

# =============================================================================
# Scope Types (Discriminated Union)
# =============================================================================


class SpecimenScope(BaseModel):
    """Scope for specimen-based evaluation (e.g., ducktape/2025-11-26-00)."""

    tag: Literal["specimen"] = "specimen"
    specimen_slug: SpecimenSlug

    model_config = ConfigDict(frozen=True)

    @property
    def split(self) -> Split:
        """Compute split from specimen membership."""
        return get_split(self.specimen_slug)

    def scope_id(self) -> str:
        """Compute scope identifier for path construction.

        Format: specimen:{project}/{date}
        Example: specimen:ducktape/2025-11-26-00
        """
        return f"specimen:{self.specimen_slug}"


class FileScope(BaseModel):
    """Scope for file-based evaluation (standalone file analysis)."""

    tag: Literal["file"] = "file"
    path: Path

    model_config = ConfigDict(frozen=True)

    @property
    def split(self) -> Split:
        """File-based runs default to train split."""
        return Split.TRAIN

    def scope_id(self) -> str:
        """Compute scope identifier for path construction.

        Format: file:{path_stem}
        Example: file:my_module
        """
        return f"file:{self.path.stem}"


# Discriminated union for scope types
Scope = Annotated[SpecimenScope | FileScope, Field(discriminator="tag")]


# =============================================================================
# Critic Run Models
# =============================================================================


class CriticInput(BaseModel):
    """Input for a critic run (codebase → candidate issues)."""

    scope: Scope
    model: str = Field(description="LLM model identifier (e.g., 'claude-sonnet-4')")
    prompt_hash: str | None = Field(
        default=None, description="Hash of the prompt template for reproducibility tracking"
    )
    notes: str | None = Field(default=None, description="Optional human notes about this run")

    model_config = ConfigDict(extra="forbid")


class CriticSuccess(BaseModel):
    """Successful critic output."""

    tag: Literal["success"] = "success"
    result: CriticSubmitPayload = Field(description="Successful critique with issues and optional notes")
    timestamp: datetime = Field(default_factory=datetime.now, description="When the critique completed")

    model_config = ConfigDict(frozen=True)


class CriticFailure(BaseModel):
    """Failed critic output."""

    tag: Literal["failure"] = "failure"
    error: CriticErrorPayload = Field(description="Error details explaining why critique failed")
    timestamp: datetime = Field(default_factory=datetime.now, description="When the failure occurred")

    model_config = ConfigDict(frozen=True)


# Discriminated union for critic output
CriticOutput = Annotated[CriticSuccess | CriticFailure, Field(discriminator="tag")]


# =============================================================================
# Grader Run Models
# =============================================================================


class GraderInput(BaseModel):
    """Input for a grader run (critique + specimen → metrics).

    Embeds the full CriticOutput for type safety and validation.
    Optional critic_run_ref tracks provenance when this grader run
    follows a standalone critic run.
    """

    scope: Scope
    critic_result: CriticOutput = Field(description="Full critic output (embedded, not path reference)")
    critic_run_ref: str | None = Field(
        default=None, description="Optional reference to the critic run directory for provenance tracking"
    )
    model: str = Field(description="LLM model identifier for the grader")
    notes: str | None = Field(default=None, description="Optional human notes about this grading run")

    model_config = ConfigDict(extra="forbid")

    @classmethod
    def from_critic_output(
        cls, critic_input: CriticInput, critic_output: CriticOutput, *, model: str, critic_run_ref: str | None = None
    ) -> GraderInput:
        """Factory: construct GraderInput from a CriticInput + CriticOutput.

        Preserves scope and adds the full critic result.
        """
        return cls(scope=critic_input.scope, critic_result=critic_output, critic_run_ref=critic_run_ref, model=model)


class GraderOutput(BaseModel):
    """Output from a grader run (metrics + detailed coverage).

    Wraps GradeSubmitInput which contains all the rich type-safe models:
    - Typed IDs (TruePositiveID, FalsePositiveID, InputIssueID)
    - CanonicalTPCoverage with recall credits
    - CanonicalFPCoverage
    - NovelIssueReasoning
    - ReportedIssueRatios
    """

    grade: GradeSubmitInput = Field(description="Full grading result with detailed coverage and metrics")
    timestamp: datetime = Field(default_factory=datetime.now, description="When the grading completed")

    model_config = ConfigDict(extra="forbid")

    @property
    def recall(self) -> float:
        """Binary recall (0-1) from the grading result."""
        return self.grade.recall

    @property
    def coverage_recall(self) -> float | None:
        """Fractional recall from recall credits (0-1), if computed."""
        total_canonical_tps = len(self.grade.canonical_tp_coverage)
        if total_canonical_tps == 0:
            return None
        # Sum recall credits, clamping each canonical's total credit to 1.0
        total_credit = sum(min(1.0, cov.recall_credit) for cov in self.grade.canonical_tp_coverage.values())
        return total_credit / total_canonical_tps


# =============================================================================
# Orchestrated Eval Models (Full-Split Evals)
# =============================================================================


@dataclass(frozen=True)
class SpecimenEvalResult:
    """Result of evaluating a single specimen (critic + grader)."""

    specimen_slug: SpecimenSlug
    critic_output: CriticOutput
    grader_output: GraderOutput | None  # None if critic failed


class FullSplitEvalInput(BaseModel):
    """Input for a full-split evaluation session (runs over one whole split).

    Orchestrated eval: runs critic + grader for every specimen in the split.
    """

    split: Split = Field(description="Which split to evaluate (train/valid/test)")
    critic_model: str = Field(description="LLM model for critic runs")
    grader_model: str = Field(description="LLM model for grader runs")
    critic_prompt_hash: str | None = Field(default=None, description="Hash of critic prompt template")
    notes: str | None = Field(default=None, description="Optional human notes about this eval session")

    model_config = ConfigDict(extra="forbid")


class FullSplitEvalOutput(BaseModel):
    """Output from a full-split evaluation session.

    Contains results for all specimens in the split.
    """

    split: Split = Field(description="Which split was evaluated")
    specimen_results: list[SpecimenEvalResult] = Field(
        default_factory=list, description="Per-specimen results (critic + grader)"
    )
    timestamp: datetime = Field(default_factory=datetime.now, description="When the eval session completed")

    model_config = ConfigDict(extra="forbid")

    @property
    def total_specimens(self) -> int:
        """Total number of specimens evaluated."""
        return len(self.specimen_results)

    @property
    def successful_critiques(self) -> int:
        """Number of specimens where critic succeeded."""
        return sum(1 for r in self.specimen_results if isinstance(r.critic_output, CriticSuccess))

    @property
    def failed_critiques(self) -> int:
        """Number of specimens where critic failed."""
        return sum(1 for r in self.specimen_results if isinstance(r.critic_output, CriticFailure))

    @property
    def avg_recall(self) -> float | None:
        """Average recall across all successfully graded specimens."""
        successful_grades = [r.grader_output.recall for r in self.specimen_results if r.grader_output is not None]
        if not successful_grades:
            return None
        return sum(successful_grades) / len(successful_grades)

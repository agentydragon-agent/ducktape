"""Run managers for properties evaluation (execution + persistence).

Defines AgentRun base class and concrete run classes (CriticRun, GraderRun, FullSplitEvalRun)
that handle:
- Run directory creation (never parse paths - always compute from typed objects)
- Input/output persistence (JSON + structured models)
- Run metadata tracking
- Factory methods for loading existing runs from disk

Path structure (computed from scope/run type):
- Atomic runs: runs/{split}/{run_type}/{scope_id}/{timestamp}/
- Orchestrated evals: runs/evals/full-split:{split}/{timestamp}/

Example paths:
- runs/train/critic/specimen:ducktape/2025-11-26-00/20250127T153045/
- runs/valid/grader/specimen:ducktape/2025-11-21-repo/20250127T153145/
- runs/evals/full-split:train/20250127T160000/
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
import json
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel

from adgn.agent.handler import BaseHandler
from adgn.openai_utils.model import OpenAIModelProto
from adgn.props.agent_runners import run_critic_agent, run_grader_agent
from adgn.props.critic import CriticErrorPayload
from adgn.props.run_models import (
    CriticFailure,
    CriticInput,
    CriticOutput,
    CriticSuccess,
    FullSplitEvalInput,
    FullSplitEvalOutput,
    GraderInput,
    GraderOutput,
    SpecimenScope,
)
from adgn.props.runs_context import RunsContext
from adgn.props.specimens.registry import SpecimenRegistry

# Type variables for generic run manager
TInput = TypeVar("TInput", bound=BaseModel)
TOutput = TypeVar("TOutput")

# Type variables for load_input/load_output (independent of class type params)
T_Input = TypeVar("T_Input", bound=BaseModel)
T_Output = TypeVar("T_Output", bound=BaseModel)


class AgentRun(ABC, Generic[TInput, TOutput]):
    """Base class for agent run management (execution + persistence).

    Subclasses implement:
    - run_type: string identifier for the run type (e.g., "critic", "grader")
    - execute(): run logic that produces output
    - _build_run_path(): compute path from input (never parse)

    All I/O happens through typed Pydantic models; JSON persistence is internal.
    """

    def __init__(self, input_data: TInput, *, ctx: RunsContext):
        """Initialize run with typed input.

        Args:
            input_data: Typed input model (CriticInput, GraderInput, etc.)
            ctx: RunsContext for path derivation (injected from CLI/entry point)
        """
        self.input_data = input_data
        self.ctx = ctx
        self.run_dir: Path | None = None
        self.output_data: TOutput | None = None

    @property
    @abstractmethod
    def run_type(self) -> str:
        """Run type identifier (e.g., 'critic', 'grader', 'full-split-eval')."""
        ...

    @abstractmethod
    def _build_run_path(self, timestamp: datetime) -> Path:
        """Compute run directory path from input + timestamp.

        NEVER parse paths - always construct from typed scope/split/timestamp.

        Args:
            timestamp: Run timestamp for uniqueness

        Returns:
            Absolute path to run directory
        """
        ...

    # NOTE: execute() is not abstract because subclasses need different signatures
    # CriticRun.execute(client, system_prompt, user_prompt, ...)
    # GraderRun.execute(client, scope_text, ...)
    # Subclasses must implement execute() with their specific required parameters

    def _ensure_run_dir(self, timestamp: datetime | None = None) -> Path:
        """Create run directory if needed and return path.

        Args:
            timestamp: Optional timestamp (defaults to now)

        Returns:
            Absolute path to run directory
        """
        if self.run_dir is not None:
            return self.run_dir

        ts = timestamp or datetime.now()
        self.run_dir = self._build_run_path(ts)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        return self.run_dir

    def save_input(self) -> Path:
        """Persist input to run directory as input.json.

        Returns:
            Path to saved input file
        """
        run_dir = self._ensure_run_dir()
        input_path = self.ctx.run_input_path(run_dir)
        input_path.write_text(self.input_data.model_dump_json(indent=2))
        return input_path

    def save_output(self, output: TOutput) -> Path:
        """Persist output to run directory as output.json.

        Args:
            output: Typed output model

        Returns:
            Path to saved output file
        """
        run_dir = self._ensure_run_dir()
        self.output_data = output
        output_path = self.ctx.run_output_path(run_dir)

        # Serialize output (handle discriminated unions properly)
        if isinstance(output, BaseModel):
            output_path.write_text(output.model_dump_json(indent=2))
        else:
            # For non-Pydantic outputs (shouldn't happen in current design)
            output_path.write_text(json.dumps(output, indent=2, default=str))

        return output_path

    # NOTE: No unified run() method since execute() signatures vary by subclass
    # Typical pattern:
    #   1. run.save_input()
    #   2. output = await run.execute(...specific params...)
    #   3. run.save_output(output)

    @classmethod
    def load_input(cls, run_dir: Path, input_type: type[T_Input], ctx: RunsContext) -> T_Input:
        """Load input from run directory.

        Args:
            run_dir: Path to run directory
            input_type: Pydantic model type for input
            ctx: RunsContext for path derivation

        Returns:
            Typed input model
        """
        input_path = ctx.run_input_path(run_dir)
        return input_type.model_validate_json(input_path.read_text())

    @classmethod
    def load_output(cls, run_dir: Path, output_type: type[T_Output], ctx: RunsContext) -> T_Output:
        """Load output from run directory.

        Args:
            run_dir: Path to run directory
            output_type: Pydantic model type for output (must be BaseModel subclass)
            ctx: RunsContext for path derivation

        Returns:
            Typed output model

        Raises:
            TypeError: If output_type is not a Pydantic BaseModel subclass
        """
        output_path = ctx.run_output_path(run_dir)
        if not (isinstance(output_type, type) and issubclass(output_type, BaseModel)):
            raise TypeError(f"output_type must be a Pydantic BaseModel subclass, got {output_type}")
        return output_type.model_validate_json(output_path.read_text())


# =============================================================================
# Concrete Run Implementations
# =============================================================================


class CriticRun(AgentRun[CriticInput, CriticOutput]):
    """Critic run: codebase → candidate issues."""

    @property
    def run_type(self) -> str:
        return "critic"

    def _build_run_path(self, timestamp: datetime) -> Path:
        """Compute path: runs/{split}/critic/{scope_id}/{timestamp}/

        Example: runs/train/critic/specimen:ducktape/2025-11-26-00/20250127T153045/
        """
        scope = self.input_data.scope
        split = scope.split.value
        scope_id = scope.scope_id()
        ts_str = timestamp.strftime("%Y%m%dT%H%M%S")

        return self.ctx.base_dir / split / self.run_type / scope_id / ts_str

    async def execute(
        self,
        *,
        client: OpenAIModelProto,
        system_prompt: str,
        user_prompt: str,
        mount_properties: bool = False,
        extra_handlers: tuple[BaseHandler, ...] = (),
    ) -> CriticOutput:
        """Execute critic agent to produce candidate issues.

        Args:
            client: OpenAI-compatible client for LLM calls
            system_prompt: System prompt for the critic agent
            user_prompt: User prompt (analysis scope description)
            mount_properties: Whether to mount /props directory (False for prompt eval)
            extra_handlers: Additional handlers (e.g., CostTrackingHandler, DisplayEventsHandler)

        Returns:
            CriticSuccess with critique payload, or CriticFailure with error
        """
        # Only SpecimenScope is currently supported
        if not isinstance(self.input_data.scope, SpecimenScope):
            error = CriticErrorPayload(message=f"Unsupported scope type: {self.input_data.scope.tag}")
            return CriticFailure(error=error, timestamp=datetime.now())

        # Ensure run directory exists
        run_dir = self._ensure_run_dir()

        # Load and hydrate specimen
        try:
            async with SpecimenRegistry.load_and_hydrate(self.input_data.scope.specimen_slug) as (rec, content_root):
                # Run critic agent (wraps existing agent_runners.py logic)
                # Transcript goes directly into run_dir (no extra nesting)
                result = await run_critic_agent(
                    specimen_rec=rec,
                    content_root=content_root,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    client=client,
                    transcript_dir=run_dir,
                    mount_properties=mount_properties,
                    extra_handlers=extra_handlers,
                )
                # Return success
                return CriticSuccess(result=result, timestamp=datetime.now())

        except RuntimeError as e:
            # Critic failed - return failure
            error = CriticErrorPayload(message=str(e))
            return CriticFailure(error=error, timestamp=datetime.now())


class GraderRun(AgentRun[GraderInput, GraderOutput]):
    """Grader run: critique + specimen → metrics."""

    @property
    def run_type(self) -> str:
        return "grader"

    def _build_run_path(self, timestamp: datetime) -> Path:
        """Compute path: runs/{split}/grader/{scope_id}/{timestamp}/

        Example: runs/valid/grader/specimen:ducktape/2025-11-21-repo/20250127T153145/
        """
        scope = self.input_data.scope
        split = scope.split.value
        scope_id = scope.scope_id()
        ts_str = timestamp.strftime("%Y%m%dT%H%M%S")

        return self.ctx.base_dir / split / self.run_type / scope_id / ts_str

    async def execute(
        self,
        *,
        client: OpenAIModelProto,
        scope_text: str,
        extra_handlers: tuple[BaseHandler, ...] = (),
        verbose: bool = False,
        verbose_prefix: str = "",
    ) -> GraderOutput:
        """Execute grader agent to produce metrics and detailed coverage.

        Args:
            client: OpenAI-compatible client for LLM calls
            scope_text: Description of analysis scope (e.g., "Specimen: ducktape/2025-11-26-00")
            extra_handlers: Additional handlers (e.g., CostTrackingHandler)
            verbose: If True, create RichDisplayHandler with proper server wiring
            verbose_prefix: Prefix for RichDisplayHandler output

        Returns:
            GraderOutput with detailed grading metrics

        Raises:
            RuntimeError: If grader fails to submit or critic result is a failure
        """
        # Only SpecimenScope is currently supported
        if not isinstance(self.input_data.scope, SpecimenScope):
            raise RuntimeError(f"Unsupported scope type: {self.input_data.scope.tag}")

        # Extract critique from critic_result (must be CriticSuccess)
        if not isinstance(self.input_data.critic_result, CriticSuccess):
            raise RuntimeError(f"Grader requires successful critique, got {self.input_data.critic_result.tag}")

        critique = self.input_data.critic_result.result

        # Ensure run directory exists
        run_dir = self._ensure_run_dir()

        # Load and hydrate specimen
        async with SpecimenRegistry.load_and_hydrate(self.input_data.scope.specimen_slug) as (rec, content_root):
            # Run grader agent (wraps existing agent_runners.py logic)
            # Transcript goes directly into run_dir (no extra nesting)
            grade = await run_grader_agent(
                specimen_rec=rec,
                content_root=content_root,
                critique=critique,
                canonical_issues=None,  # Use specimen defaults
                known_fps=None,  # Use specimen defaults
                scope_text=scope_text,
                client=client,
                transcript_dir=run_dir,
                extra_handlers=extra_handlers,
                verbose=verbose,
                verbose_prefix=verbose_prefix,
            )

            # Return grader output
            return GraderOutput(grade=grade, timestamp=datetime.now())


class FullSplitEvalRun(AgentRun[FullSplitEvalInput, FullSplitEvalOutput]):
    """Full-split eval: orchestrated critic + grader for all specimens in a split."""

    @property
    def run_type(self) -> str:
        return "full-split-eval"

    def _build_run_path(self, timestamp: datetime) -> Path:
        """Compute path: runs/evals/full-split:{split}/{timestamp}/

        Example: runs/evals/full-split:train/20250127T160000/
        """
        split = self.input_data.split.value
        ts_str = timestamp.strftime("%Y%m%dT%H%M%S")

        return self.ctx.base_dir / "evals" / f"full-split:{split}" / ts_str

    async def execute(self) -> FullSplitEvalOutput:
        """Execute full-split eval: critic + grader for all specimens.

        TODO: Implement orchestrated execution:
        1. Load all specimens for the split
        2. For each specimen:
           a. Run critic (CriticRun)
           b. If critic succeeds, run grader (GraderRun)
        3. Aggregate results into FullSplitEvalOutput

        For now, raises NotImplementedError.
        """
        raise NotImplementedError("FullSplitEvalRun.execute() not yet implemented")

"""Prompt Evaluation MCP server.

- Server name: prompt_eval
 - Tool: test_prompt(PromptEvalArgs) -> PromptEvalOutput (typed metrics list)

Behavior:
- On each call, iterates all known specimens (SpecimenRegistry), runs the critic and grader, and returns typed metrics.
- Persists artifacts under props/runs/prompt_optimize/<ts>/<round>/<specimen>/ including critic.json, grade.json, and transcripts.
- Failure semantics: if any specimen run fails, this tool raises an Exception. FastMCP translates
  this into an isError tool payload. Callers should treat such results as tool errors.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import partial
import json
import logging
from pathlib import Path

from fastmcp.client import Client
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field

from adgn.agent.agent import MiniCodex

# from adgn.agent.event_renderer import DisplayEventsHandler
from adgn.agent.handler import BaseHandler
from adgn.agent.reducer import GateUntil
from adgn.agent.rich_display import RichDisplayHandler
from adgn.agent.transcript_handler import TranscriptHandler
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.compositor.setup import mount_standard_inproc_servers
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.openai_utils.model import OpenAIModelProto
from adgn.props.agent_runners import CostTrackingHandler
from adgn.props.critic import CriticSubmitPayload, CriticSubmitState, attach_critic_submit
from adgn.props.docker_env import properties_docker_spec
from adgn.props.grade_runner import grade_critic_output
from adgn.props.grader import ReportedIssueRatios
from adgn.props.lint_issue import BootstrapInspectHandler
from adgn.props.per_file_eval import run_per_file_eval
from adgn.props.prompts.util import build_scope_text, render_prompt_template
from adgn.props.prop_utils import pkg_dir
from adgn.props.specimens.registry import SpecimenRegistry
from adgn.props.splits import get_train_specimens, get_valid_specimens

logger = logging.getLogger(__name__)

# Role identifiers for verbose prefixes
ROLE_CRITIC = "CRITIC"
ROLE_GRADER = "GRADER"


def _role_prefix(specimen: str, role: str) -> str:
    """Build verbose prefix for display handler: '[specimen/ROLE] '."""
    return f"  [{specimen}/{role}] "


async def _run_critic_and_grader(
    specimen: str,
    prompt_text: str,
    client: OpenAIModelProto,
    eval_dir: Path,
    out_dir: Path,
    *,
    agent_model: str,
    verbose: bool,
) -> MetricsRow:
    """Run critic and grader on one specimen; return MetricsRow with agent-computed metrics."""
    out_dir.mkdir(parents=True, exist_ok=True)

    cost_tracker = CostTrackingHandler()
    extra_handlers = (cost_tracker,)

    # Run critic
    critic_obj = await _run_critic_for_specimen(
        specimen,
        prompt_text,
        client,
        eval_dir,
        agent_model=agent_model,
        extra_handlers=extra_handlers,
        verbose=verbose,
        verbose_prefix=_role_prefix(specimen, ROLE_CRITIC),
    )
    critic_cost = cost_tracker.total_cost

    # Reset for grader
    cost_tracker.total_cost = 0.0

    # Run grader
    grade_obj = await grade_critic_output(
        specimen,
        critic_obj,
        client,
        transcript_out_dir=out_dir,
        extra_handlers=extra_handlers,
        verbose=verbose,
        verbose_prefix=_role_prefix(specimen, ROLE_GRADER),
    )
    grader_cost = cost_tracker.total_cost

    # Persist grade
    (out_dir / "grade.json").write_text(grade_obj.model_dump_json(indent=2), encoding="utf-8")

    # Extract agent-computed metrics (recall and reported_issue_ratios)
    return MetricsRow(
        specimen=specimen,
        recall=grade_obj.recall,
        reported_issue_ratios=grade_obj.reported_issue_ratios,
        cost=critic_cost + grader_cost,
    )


async def _run_split_eval(
    specimens: list[str],
    split_name: str,
    prompt_path: str,
    *,
    client: OpenAIModelProto,
    agent_model: str,
    evals_dir: Path,
    state: PromptEvalState,
    read_prompt_file: Callable[[str], str],
    translate_host_path: Callable[[Path], str],
) -> tuple[Path, list[MetricsRow], float, float | None]:
    """Run evaluation on a split; return (eval_dir, metrics, cost, budget_remaining).

    Shared logic for eval_train_split and eval_valid_split:
    - Setup (read prompt, check budget, create eval dir under split-specific subdir)
    - Parallel execution (run critic+grader on all specimens)
    - Error handling (persist errors.json, raise on failures)
    - Cost tracking (sum costs, update state, compute remaining budget)

    Directory structure ensures validation results are NOT mounted to container:
    - Train: evals_dir/train/eval_<ts>/ -> mounted to /artifacts/prompt_evals/train/...
    - Valid: evals_dir/valid/eval_<ts>/ -> NOT mounted (prevents information leakage)
    """
    prompt_text = read_prompt_file(prompt_path)

    # Budget check before starting work
    state.check_budget_before_work()

    # Create eval directory under split-specific subdirectory
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    split_dir = evals_dir / split_name
    split_dir.mkdir(parents=True, exist_ok=True)
    eval_dir = split_dir / f"eval_{ts}"
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")
    logger.info("eval_%s_split: %s", split_name, eval_dir)

    # Process each specimen once (in parallel)
    process_one = partial(
        _run_critic_and_grader,
        prompt_text=prompt_text,
        client=client,
        eval_dir=eval_dir,
        agent_model=agent_model,
        verbose=state.verbose,
    )

    # Run all specimens in parallel (each processed exactly once)
    results = await asyncio.gather(
        *[process_one(specimen=s, out_dir=eval_dir / s) for s in specimens], return_exceptions=True
    )

    # Separate successes from failures
    metrics: list[MetricsRow] = [r for r in results if not isinstance(r, BaseException)]
    failures: list[BaseException] = [r for r in results if isinstance(r, BaseException)]

    if failures:
        total_specimens = len(metrics) + len(failures)
        logger.error(f"{len(failures)}/{total_specimens} {split_name} specimens failed")
        # Persist error summary
        errors = [{"type": type(e).__name__, "message": str(e)} for e in failures]
        errors_file = eval_dir / "errors.json"
        errors_file.write_text(json.dumps(errors, indent=2), encoding="utf-8")
        # Translate host path to container path for error message
        container_errors_path = translate_host_path(errors_file)
        raise RuntimeError(f"{len(failures)}/{len(results)} specimens failed. See {container_errors_path} for details.")

    # Calculate total cost from MetricsRow.cost
    cost = sum(m.cost for m in metrics)
    state.total_cost += cost

    budget_remaining = state.budget_limit - state.total_cost if state.budget_limit else None

    return eval_dir, metrics, cost, budget_remaining


class PromptEvalArgs(BaseModel):
    """Input model for test_prompt (flat helper for tests, deprecated)."""

    prompt: str
    model_config = ConfigDict(extra="forbid")


class EvalFileInput(BaseModel):
    """Input for eval_file: evaluate prompt on one file."""

    prompt_path: str = Field(description="Container path to prompt file (e.g., /workspace/prompts/v1.txt)")
    specimen: str = Field(description="Specimen slug (e.g., ducktape/2025-11-20-adgn)")
    file_path: str = Field(description="Relative path within specimen to evaluate")

    model_config = ConfigDict(extra="forbid")


class EvalSpecimenInput(BaseModel):
    """Input for eval_specimen: evaluate prompt on one specimen."""

    prompt_path: str = Field(description="Container path to prompt file (e.g., /workspace/prompts/v1.txt)")
    specimen: str = Field(description="Specimen slug (e.g., ducktape/2025-11-20-adgn)")

    model_config = ConfigDict(extra="forbid")


class EvalSplitInput(BaseModel):
    """Input for eval_train_split and eval_valid_split."""

    prompt_path: str = Field(description="Container path to prompt file (e.g., /workspace/prompts/v1.txt)")

    model_config = ConfigDict(extra="forbid")


class EvalSpecimenOutput(BaseModel):
    """Output from eval_train_specimen and eval_train_specimen_file.

    Contains grader agent's primary computed metrics (recall, issue ratios).
    """

    specimen: str
    recall: float = Field(description="Weighted recall computed by grader agent (primary optimization target)")
    reported_issue_ratios: ReportedIssueRatios = Field(
        description="Breakdown of reported issues: TP/FP/unlabeled fractions"
    )
    cost: float
    budget_remaining: float | None
    detailed_artifacts_dir: str = Field(
        description="Container path to evaluation artifacts (transcripts, grades, critic output)"
    )

    model_config = ConfigDict(extra="forbid")


class EvalTrainSplitOutput(BaseModel):
    """Output from eval_train_split: detailed per-specimen metrics for analysis."""

    detailed_metrics: list[MetricsRow] = Field(
        description="Per-specimen agent-computed metrics: recall, reported_issue_ratios (tp/fp/unlabeled), cost"
    )
    specimens: list[str] = Field(description="List of specimen slugs evaluated")

    cost: float
    budget_remaining: float | None
    detailed_artifacts_dir: str = Field(
        description="Container path to evaluation artifacts (per-specimen transcripts, grades, critic outputs)"
    )

    model_config = ConfigDict(extra="forbid")


class EvalValidSplitOutput(BaseModel):
    """Output from eval_valid_split: aggregate metrics only (prevents overfitting).

    Validation provides minimal information by design:
    - Only aggregate recall and TP ratio (your optimization targets)
    - No per-specimen details (prevents overfitting to validation specimens)
    - No detailed_artifacts_dir (prevents agent from reading detailed results)
    """

    aggregate_recall: float = Field(description="Average recall across validation specimens (YOUR TARGET METRIC)")
    aggregate_tp_ratio: float = Field(
        description="Average TP ratio (fraction of reported issues matching canonical TPs)"
    )
    specimen_count: int = Field(description="Number of validation specimens evaluated")

    cost: float
    budget_remaining: float | None

    model_config = ConfigDict(extra="forbid")


class MetricsRow(BaseModel):
    """Typed per-specimen metrics row (agent-computed primary metrics only)."""

    specimen: str
    recall: float
    reported_issue_ratios: ReportedIssueRatios
    cost: float = Field(description="Total cost for this specimen (critic + grader)")

    model_config = ConfigDict(extra="forbid")


class PromptEvalOutput(BaseModel):
    metrics: list[MetricsRow]

    model_config = ConfigDict(extra="forbid")


async def _run_critic_for_specimen(
    specimen: str,
    system_prompt: str,
    client: OpenAIModelProto,
    run_dir: Path,
    *,
    agent_model: str = "gpt-5",
    extra_handlers: tuple[BaseHandler, ...] = (),
    verbose: bool = False,
    verbose_prefix: str = "",
) -> CriticSubmitPayload:
    """Run critic with a custom system prompt (no properties mount); return CriticSubmitPayload model and persist.

    Args:
        specimen: Specimen slug
        system_prompt: System prompt for critic
        client: OpenAI-compatible client
        run_dir: Root directory for outputs
        agent_model: Model ID for critic agent
        extra_handlers: Additional handlers (e.g., CostTrackingHandler) - excludes RichDisplayHandler
        verbose: If True, create RichDisplayHandler with proper server wiring
        verbose_prefix: Prefix for RichDisplayHandler output
    """
    critic_state = CriticSubmitState()

    # Load and hydrate specimen (single hydration, avoid wasteful re-hydrate)
    async with SpecimenRegistry.load_and_hydrate(specimen, gitconfig=None) as (rec, content_root):
        # Render user prompt with explicit scope (no property definitions mounted)
        scope_text = build_scope_text(rec.manifest.scope.include, rec.manifest.scope.exclude)
        user_prompt = render_prompt_template("critic_user_prompt.j2.md", scope_text=scope_text)
        wiring = properties_docker_spec(content_root, mount_properties=False)
        comp = Compositor("compositor")
        runtime_server = await wiring.attach(comp)
        critic_submit_server = await attach_critic_submit(comp, critic_state)

        # Collect servers for schema extraction
        servers = {wiring.server_name: runtime_server, "critic_submit": critic_submit_server}

        bootstrap = BootstrapInspectHandler(wiring)

        def _ready_state() -> bool:
            return (critic_state.result is not None) or (critic_state.error is not None)

        def _defer_bootstrap() -> bool:
            return not bootstrap._done

        handlers = [
            bootstrap,
            # Canonical per-run transcript JSONL (events.jsonl + metadata.json)
            TranscriptHandler(dest_dir=run_dir / specimen / "critic"),
            # Defer gating during first bootstrap phase to avoid Continue conflicts
            GateUntil(_ready_state, defer_when=_defer_bootstrap),
        ]

        # Add verbose display if requested (with proper server wiring)
        if verbose:
            handlers.append(RichDisplayHandler(max_lines=10, prefix=verbose_prefix, servers=servers))

        # Add other handlers (e.g., cost tracking)
        handlers.extend(extra_handlers)
        # Use the caller-provided typed client; logging is configured at the entrypoint
        model_client: OpenAIModelProto = client
        async with Client(comp) as mcp_client:
            # Mount standard servers (resources, compositor_meta, compositor_admin)
            await mount_standard_inproc_servers(compositor=comp)
            agent = await MiniCodex.create(
                model=agent_model,
                mcp_client=mcp_client,
                system=system_prompt,
                client=model_client,
                handlers=handlers,
                parallel_tool_calls=True,
            )
            await agent.run(user_prompt)
    assert (critic_state.result is not None) or (critic_state.error is not None), (
        "critic_submit.submit_result or submit_error was not called"
    )
    # Persist
    out_dir = run_dir / specimen
    out_dir.mkdir(parents=True, exist_ok=True)
    if critic_state.error is not None:
        (out_dir / "critic_error.json").write_text(critic_state.error.model_dump_json(indent=2), encoding="utf-8")
        raise RuntimeError(
            f"critic error: {critic_state.error.message}"
        )  # surfaced to caller; per-round errors.json aggregates
    assert critic_state.result is not None
    (out_dir / "critic.json").write_text(critic_state.result.model_dump_json(indent=2), encoding="utf-8")
    return critic_state.result


@dataclass
class PromptEvalState:
    """Track state across prompt_eval tool calls."""

    successful_calls: int = 0
    total_cost: float = 0.0
    budget_limit: float | None = None  # $ limit, if set
    verbose: bool = False  # If True, display inner agent events

    def check_budget_before_work(self) -> None:
        """Raise ToolError if budget is already exhausted."""
        if self.budget_limit and self.total_cost >= self.budget_limit:
            raise ToolError(
                f"Budget already exhausted: ${self.total_cost:.2f} >= ${self.budget_limit:.2f}. "
                "Cannot start new evaluation."
            )


def build_server(
    *,
    client: OpenAIModelProto,
    name: str = "prompt_eval",
    agent_model: str = "gpt-5",
    evals_base_dir: Path | None = None,
    workspace_host_path: Path | None = None,
) -> tuple[NotifyingFastMCP, PromptEvalState]:
    """Build a prompt_eval server with granular evaluation tools and budget tracking.

    Args:
        client: OpenAI client for running evaluations
        name: MCP server name
        agent_model: Model ID for inner critic agent
        evals_base_dir: Directory for evaluation results
        workspace_host_path: Host filesystem path that maps to /workspace in container
                            (needed for translating container paths to host paths)

    Layout:
    evals_base_dir/
      train/eval_<timestamp>/
        <specimen>/
          critic.json
          grade.json
          critic/events.jsonl
          grader/events.jsonl
      valid/eval_<timestamp>/
        <specimen>/
          (same structure but not mounted to container)
    """
    # Shared evaluation directory (tests may inject a tmp dir)
    evals_dir = evals_base_dir if evals_base_dir is not None else pkg_dir() / "runs" / "prompt_evals"
    evals_dir.mkdir(parents=True, exist_ok=True)

    state = PromptEvalState()

    def _validate_train_specimen(specimen: str) -> None:
        """Validate specimen is in train split; raise ToolError if not.

        Args:
            specimen: Specimen slug to validate

        Raises:
            ToolError: If specimen is not in train split
        """
        train_specimens = get_train_specimens()
        if specimen not in train_specimens:
            raise ToolError(
                f"This tool only works on train split to prevent leakage. "
                f"Specimen '{specimen}' is not in train split. "
                f"Available train specimens: {', '.join(sorted(train_specimens))}"
            )

    def _setup_eval_dir(prompt_path: str, log_context: str) -> tuple[Path, str]:
        """Setup eval directory for train split tools (eval_file, eval_specimen).

        Args:
            prompt_path: Container path to prompt file
            log_context: Context string for logging (e.g., "eval_file foo:bar.py")

        Returns:
            (eval_dir, prompt_text): Created eval directory and prompt content
        """
        prompt_text = _read_prompt_file(prompt_path)
        state.check_budget_before_work()

        # Create eval directory under train/ (will be mounted to container)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        train_dir = evals_dir / "train"
        train_dir.mkdir(parents=True, exist_ok=True)
        eval_dir = train_dir / f"eval_{ts}"
        eval_dir.mkdir(parents=True, exist_ok=True)
        (eval_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")
        logger.info("%s: %s", log_context, eval_dir)
        return eval_dir, prompt_text

    def _translate_container_path(container_path: str) -> Path:
        """Translate container path to host path.

        Raises:
            ToolError: If path cannot be translated
        """
        if workspace_host_path is None:
            raise ToolError("Path translation not configured. This server requires workspace_host_path to be set.")

        if container_path.startswith("/workspace/"):
            relative = container_path.removeprefix("/workspace/")
            return workspace_host_path / relative

        # Path is not in /workspace - cannot translate
        raise ToolError(f"Cannot translate path: {container_path}. Only /workspace/* paths are supported.")

    def _translate_host_path(host_path: Path) -> str:
        """Translate host path to container path for error messages.

        Args:
            host_path: Host filesystem path

        Returns:
            Container path string (e.g., /artifacts/prompt_evals/train/...)
            Note: Only train split paths are mounted; valid split paths return host paths.
        """
        # Check if path is under evals_dir
        try:
            relative = host_path.relative_to(evals_dir)
            # Only train split is mounted to container
            if relative.parts[0] == "train":
                return f"/artifacts/prompt_evals/{relative}"
            # Valid split is not mounted - return host path
            return str(host_path)
        except ValueError:
            # Not under evals_dir, return as-is
            return str(host_path)

    def _read_prompt_file(container_path: str) -> str:
        """Read prompt from container path.

        Raises:
            ToolError: If file not found or cannot be read
        """
        host_path = _translate_container_path(container_path)
        if not host_path.exists():
            raise ToolError(f"Prompt file not found: {container_path}")
        return host_path.read_text(encoding="utf-8")

    mcp = NotifyingFastMCP(
        name, instructions="Prompt Evaluation server — evaluate candidate critic prompts with budget tracking"
    )
    # FastMCP wraps tool Exceptions into ToolError; failures propagate as tool errors

    @mcp.tool(flat=True)
    async def eval_train_split(payload: EvalSplitInput) -> EvalTrainSplitOutput:
        """Analyze train split with detailed per-specimen metrics.

        Use this for:
        - Understanding which specimens your prompt struggles with
        - Identifying patterns in failures across multiple specimens
        - Getting detailed metrics to guide prompt improvements

        Returns detailed metrics for every train specimen plus detailed_artifacts_dir for full access to:
        - Critic transcripts: <dir>/<specimen>/critic/events.jsonl
        - Grader transcripts: <dir>/<specimen>/grader/events.jsonl
        - Results: <dir>/<specimen>/critic.json, grade.json
        """
        specimens = get_train_specimens()

        # Run split evaluation (shared logic)
        eval_dir, metrics, cost, budget_remaining = await _run_split_eval(
            specimens=specimens,
            split_name="train",
            prompt_path=payload.prompt_path,
            client=client,
            agent_model=agent_model,
            evals_dir=evals_dir,
            state=state,
            read_prompt_file=_read_prompt_file,
            translate_host_path=_translate_host_path,
        )

        # Train: detailed metrics
        if not metrics:
            raise ToolError("No metrics collected from train split")

        result = EvalTrainSplitOutput(
            detailed_metrics=metrics,
            specimens=specimens,
            cost=cost,
            budget_remaining=budget_remaining,
            detailed_artifacts_dir=_translate_host_path(eval_dir),
        )
        (eval_dir / "train_results.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return result

    @mcp.tool(flat=True)
    async def eval_valid_split(payload: EvalSplitInput) -> EvalValidSplitOutput:
        """Check validation recall (YOUR OPTIMIZATION TARGET).

        Use this to:
        - Measure how well your prompt generalizes
        - Check if improvements on train transfer to validation
        - Get your proxy metric for final test performance

        Returns ONLY aggregate metrics by design (prevents overfitting):
        - aggregate_recall: Your target metric
        - aggregate_precision: May be low due to sparse labeling
        - No per-specimen details (intentional)
        """
        specimens = get_valid_specimens()

        # Run split evaluation (shared logic)
        eval_dir, metrics, cost, budget_remaining = await _run_split_eval(
            specimens=specimens,
            split_name="valid",
            prompt_path=payload.prompt_path,
            client=client,
            agent_model=agent_model,
            evals_dir=evals_dir,
            state=state,
            read_prompt_file=_read_prompt_file,
            translate_host_path=_translate_host_path,
        )

        # Valid: aggregates only (prevents overfitting)
        if not metrics:
            raise ToolError("No metrics collected from validation split")

        # TODO: These are specimen-averaged, not issue-averaged. Specimens differ in number of issues,
        # so this treats each specimen equally regardless of its size. Consider issue-weighted averaging
        # if specimens have significantly different issue counts.
        agg_recall = sum(m.recall for m in metrics) / len(metrics)
        agg_tp_ratio = sum(m.reported_issue_ratios.tp for m in metrics) / len(metrics)

        result = EvalValidSplitOutput(
            aggregate_recall=agg_recall,
            aggregate_tp_ratio=agg_tp_ratio,
            specimen_count=len(metrics),
            cost=cost,
            budget_remaining=budget_remaining,
        )
        (eval_dir / "valid_summary.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return result

    @mcp.tool(flat=True)
    async def eval_train_specimen(payload: EvalSpecimenInput) -> EvalSpecimenOutput:
        """Evaluate a prompt on one train specimen (medium cost, ~$1-5).

        Use this to:
        - Test prompt on a specific specimen you're debugging
        - Get detailed metrics and full access to transcripts/artifacts

        Constraints:
        - Only works on train split (prevents leakage to valid/test)

        To find a specimen to evaluate, check /specimen_defs/train/ for available specimens
        and review their issues/*.libsonnet files.
        """
        _validate_train_specimen(payload.specimen)
        eval_dir, prompt_text = _setup_eval_dir(payload.prompt_path, f"eval_train_specimen {payload.specimen}")

        # Run critic + grader on specimen (returns MetricsRow with computed metrics)
        metrics_row = await _run_critic_and_grader(
            payload.specimen,
            prompt_text,
            client,
            eval_dir,
            eval_dir / payload.specimen,
            agent_model=agent_model,
            verbose=state.verbose,
        )

        state.total_cost += metrics_row.cost
        budget_remaining = state.budget_limit - state.total_cost if state.budget_limit else None

        # Construct output with agent-computed metrics
        return EvalSpecimenOutput(
            specimen=payload.specimen,
            recall=metrics_row.recall,
            reported_issue_ratios=metrics_row.reported_issue_ratios,
            cost=metrics_row.cost,
            budget_remaining=budget_remaining,
            detailed_artifacts_dir=_translate_host_path(eval_dir),
        )

    @mcp.tool(flat=True)
    async def eval_train_specimen_file(payload: EvalFileInput) -> EvalSpecimenOutput:
        """Evaluate a prompt on one file in a train specimen (fast iteration, low cost ~$0.10-0.50).

        Use this for:
        - Fast iteration on specific files during prompt development
        - Testing prompt changes on files you know are problematic

        Returns same metrics as eval_train_specimen but scoped to a single file.

        Constraints:
        - Only works on train split (prevents leakage to valid/test)
        - Only works on files with >0 issues (validates before running)

        To find files to evaluate:
        1. Check /specimen_defs/train/<specimen>/issues/*.libsonnet for issue definitions
        2. Each issue shows filesToRanges mapping which files contain issues
        3. Pick a file path and pass it to this tool
        """
        _validate_train_specimen(payload.specimen)
        eval_dir, prompt_text = _setup_eval_dir(
            payload.prompt_path, f"eval_train_specimen_file {payload.specimen}:{payload.file_path}"
        )

        # Run per-file eval with file filter (runs critic + grader on single file)
        result = await run_per_file_eval(
            specimen=payload.specimen,
            system_prompt=prompt_text,
            client=client,
            out_dir=eval_dir,
            gitconfig=None,
            file_filter=payload.file_path,
            verbose=state.verbose,
        )

        # Extract cost from per-file run results (single file in this case)
        cost = sum(run.cost for run in result.per_file_runs)
        state.total_cost += cost
        budget_remaining = state.budget_limit - state.total_cost if state.budget_limit else None

        # Extract results for the single file
        if not result.per_file_runs:
            raise RuntimeError(f"No results returned for file {payload.file_path}")

        file_result = result.per_file_runs[0]  # Only one file since we filtered

        # Extract grade and agent-computed metrics
        if file_result.grade is None:
            raise RuntimeError(f"Grading failed for file {payload.file_path}")

        if file_result.critique is None:
            raise RuntimeError(f"Critique failed for file {payload.file_path}")

        # Use agent-computed metrics directly
        return EvalSpecimenOutput(
            specimen=payload.specimen,
            recall=file_result.grade.recall,
            reported_issue_ratios=file_result.grade.reported_issue_ratios,
            cost=cost,
            budget_remaining=budget_remaining,
            detailed_artifacts_dir=_translate_host_path(eval_dir),
        )

    return mcp, state


async def attach_prompt_eval(
    comp: Compositor,
    *,
    client: OpenAIModelProto,
    name: str = "prompt_eval",
    agent_model: str = "gpt-5",
    evals_base_dir: Path | None = None,
    workspace_host_path: Path | None = None,
):
    """Attach prompt_eval in-proc; return (server, state)."""
    server, state = build_server(
        client=client,
        name=name,
        agent_model=agent_model,
        evals_base_dir=evals_base_dir,
        workspace_host_path=workspace_host_path,
    )
    await comp.mount_inproc(name, server)
    return server, state

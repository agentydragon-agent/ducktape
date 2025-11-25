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
from dataclasses import dataclass
from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Any

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
from adgn.props.grader import GradeMetrics
from adgn.props.lint_issue import BootstrapInspectHandler
from adgn.props.per_file_eval import run_per_file_eval
from adgn.props.prompts.util import build_scope_text, render_prompt_template
from adgn.props.prop_utils import pkg_dir
from adgn.props.specimens.registry import SpecimenRegistry
from adgn.props.splits import Split, get_train_specimens, get_valid_specimens

logger = logging.getLogger(__name__)


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
    """Input for eval_split: evaluate prompt on train/valid/test split."""

    prompt_path: str = Field(description="Container path to prompt file (e.g., /workspace/prompts/v1.txt)")
    split: Split = Field(description="Which split to evaluate (train, valid, or test)")

    model_config = ConfigDict(extra="forbid")


class EvalFileOutput(BaseModel):
    """Output from eval_file."""

    specimen: str
    file_path: str
    issues_in_file: list[str]
    detected_issues: list[str]
    detection_rate: float

    cost: float
    eval_dir: str

    model_config = ConfigDict(extra="forbid")


class EvalSpecimenOutput(BaseModel):
    """Output from eval_specimen."""

    specimen: str
    metrics: GradeMetrics
    cost: float
    eval_dir: str

    model_config = ConfigDict(extra="forbid")


class EvalSplitOutput(BaseModel):
    """Output from eval_split.

    Structure is uniform regardless of split; fields populated based on split type:
    - train: detailed_metrics + specimens populated
    - valid: aggregate metrics only
    - test: not returned (raises ToolError)
    """

    split: str  # which split was evaluated

    # Detailed metrics (train only)
    detailed_metrics: list[dict[str, Any]] | None = None
    specimens: list[str] | None = None

    # Aggregate metrics (valid only)
    aggregate_recall: float | None = None
    aggregate_precision: float | None = None
    specimen_count: int | None = None
    issue_count: int | None = None

    cost: float
    total_cost_so_far: float
    budget_remaining: float | None
    eval_dir: str

    model_config = ConfigDict(extra="forbid")


class MetricsRow(BaseModel):
    """Typed per-specimen metrics row returned by prompt_eval.test_prompt."""

    specimen: str
    metrics: GradeMetrics
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
    rec = SpecimenRegistry.load_strict(specimen)
    critic_state = CriticSubmitState()

    # Render user prompt with explicit scope (no property definitions mounted)
    scope_text = build_scope_text(
        rec.manifest.scope.include, rec.manifest.scope.exclude
    )
    user_prompt = render_prompt_template(
        "critic_user_prompt.j2.md", scope_text=scope_text
    )

    async with rec.hydrated_copy(gitconfig=None) as content_root:
        wiring = properties_docker_spec(content_root, mount_properties=False)
        comp = Compositor("compositor")
        runtime_server = await wiring.attach(comp)
        critic_submit_server = await attach_critic_submit(comp, critic_state)

        # Collect servers for schema extraction
        servers = {
            wiring.server_name: runtime_server,
            "critic_submit": critic_submit_server,
        }

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
            handlers.append(RichDisplayHandler(
                max_lines=10,
                prefix=verbose_prefix,
                servers=servers,
            ))

        # Add other handlers (e.g., cost tracking)
        handlers.extend(extra_handlers)
        # Use the caller-provided typed client; logging is configured at the entrypoint
        model_client: OpenAIModelProto = client
        async with Client(comp) as mcp_client:
            # Mount standard servers (resources, compositor_meta, compositor_admin)
            await mount_standard_inproc_servers(compositor=comp, gateway_client=mcp_client)
            agent = await MiniCodex.create(
                model=agent_model,
                mcp_client=mcp_client,
                system=system_prompt,
                client=model_client,
                handlers=handlers,
                parallel_tool_calls=True,
            )
            await agent.run(user_prompt)
    assert (critic_state.result is not None) or (
        critic_state.error is not None
    ), "critic_submit.submit_result or submit_error was not called"
    # Persist
    out_dir = run_dir / specimen
    out_dir.mkdir(parents=True, exist_ok=True)
    if critic_state.error is not None:
        (out_dir / "critic_error.json").write_text(
            critic_state.error.model_dump_json(indent=2), encoding="utf-8"
        )
        raise RuntimeError(
            f"critic error: {critic_state.error.message}"
        )  # surfaced to caller; per-round errors.json aggregates
    assert critic_state.result is not None
    (out_dir / "critic.json").write_text(
        critic_state.result.model_dump_json(indent=2), encoding="utf-8"
    )
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
      eval_<timestamp>/
        <specimen>/
          critic.json
          grade.json
          critic/events.jsonl
          grader/events.jsonl
    """
    # Shared evaluation directory (tests may inject a tmp dir)
    evals_dir = (
        evals_base_dir
        if evals_base_dir is not None
        else pkg_dir() / "runs" / "prompt_evals"
    )
    evals_dir.mkdir(parents=True, exist_ok=True)

    state = PromptEvalState()

    def _translate_container_path(container_path: str) -> Path:
        """Translate container path to host path.

        Raises:
            ToolError: If path cannot be translated
        """
        if workspace_host_path is None:
            raise ToolError(
                "Path translation not configured. "
                "This server requires workspace_host_path to be set."
            )

        if container_path.startswith("/workspace/"):
            relative = container_path.removeprefix("/workspace/")
            return workspace_host_path / relative

        # Path is not in /workspace - cannot translate
        raise ToolError(
            f"Cannot translate path: {container_path}. "
            f"Only /workspace/* paths are supported."
        )

    def _translate_host_path(host_path: Path) -> str:
        """Translate host path to container path for error messages.

        Args:
            host_path: Host filesystem path

        Returns:
            Container path string (e.g., /artifacts/prompt_evals/...)
        """
        # Check if path is under evals_dir
        try:
            relative = host_path.relative_to(evals_dir)
            return f"/artifacts/prompt_evals/{relative}"
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
        name,
        instructions="Prompt Evaluation server — evaluate candidate critic prompts with budget tracking",
    )
    # FastMCP wraps tool Exceptions into ToolError; failures propagate as tool errors

    @mcp.tool(flat=True)
    async def eval_split(payload: EvalSplitInput) -> EvalSplitOutput:
        """Evaluate a prompt on train/valid/test split.

        Returns:
        - train: detailed per-specimen metrics
        - valid: aggregate metrics only
        - test: raises ToolError (hidden from agent)
        """
        if payload.split == "test":
            raise ToolError("Test split is withheld.")

        prompt_text = _read_prompt_file(payload.prompt_path)

        # Get specimens for requested split
        if payload.split == "train":
            specimens = get_train_specimens()
        elif payload.split == "valid":
            specimens = get_valid_specimens()
        else:
            raise ToolError(
                f"Unknown split: {payload.split}. Must be 'train', 'valid', or 'test'."
            )

        # Budget check before starting work
        state.check_budget_before_work()

        # Create eval directory
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        eval_dir = evals_dir / f"eval_{ts}"
        eval_dir.mkdir(parents=True, exist_ok=True)
        (eval_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")
        logger.info("eval_split %s: %s", payload.split, eval_dir)

        # Process each specimen once (in parallel)
        async def process_one(specimen: str) -> MetricsRow:
            """Process one specimen and return metrics with cost."""
            out_dir = eval_dir / specimen
            out_dir.mkdir(parents=True, exist_ok=True)

            # Set up cost tracking (no RichDisplayHandler here - created inside with servers)
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
                verbose=state.verbose,
                verbose_prefix=f"  [{specimen}] ",
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
                verbose=state.verbose,
                verbose_prefix=f"  [{specimen}] ",
            )
            grader_cost = cost_tracker.total_cost

            (out_dir / "grade.json").write_text(
                grade_obj.model_dump_json(indent=2), encoding="utf-8"
            )

            # Construct MetricsRow with nested GradeMetrics
            total_specimen_cost = critic_cost + grader_cost
            return MetricsRow(
                specimen=specimen,
                metrics=grade_obj.metrics,
                cost=total_specimen_cost,
            )

        # Run all specimens in parallel (each processed exactly once)
        results = await asyncio.gather(
            *[process_one(s) for s in specimens], return_exceptions=True
        )

        # Separate successes from failures
        metrics: list[MetricsRow] = [
            r for r in results if not isinstance(r, BaseException)
        ]
        failures: list[BaseException] = [
            r for r in results if isinstance(r, BaseException)
        ]

        if failures:
            total_specimens = len(metrics) + len(failures)
            logger.error(
                f"{len(failures)}/{total_specimens} specimens failed in {payload.split} split"
            )
            # Persist error summary
            errors = [{"type": type(e).__name__, "message": str(e)} for e in failures]
            errors_file = eval_dir / "errors.json"
            errors_file.write_text(
                json.dumps(errors, indent=2), encoding="utf-8"
            )
            # Translate host path to container path for error message
            container_errors_path = _translate_host_path(errors_file)
            raise RuntimeError(
                f"{len(failures)}/{len(results)} specimens failed. "
                f"See {container_errors_path} for details."
            )

        # Calculate total cost from MetricsRow.cost
        cost = sum(m.cost for m in metrics)
        state.total_cost += cost

        budget_remaining = (
            state.budget_limit - state.total_cost if state.budget_limit else None
        )

        # Build output based on split
        if payload.split == "train":
            # Train: detailed metrics
            metrics_dicts = [m.model_dump() for m in metrics]
            result = EvalSplitOutput(
                split=payload.split,
                detailed_metrics=metrics_dicts,
                specimens=specimens,
                aggregate_recall=None,
                aggregate_precision=None,
                specimen_count=None,
                issue_count=None,
                cost=cost,
                total_cost_so_far=state.total_cost,
                budget_remaining=budget_remaining,
                eval_dir=_translate_host_path(eval_dir),
            )
            (eval_dir / "train_results.json").write_text(
                result.model_dump_json(indent=2), encoding="utf-8"
            )
            return result
        # valid
        # Valid: aggregates only
        agg_recall = sum(m.metrics.recall for m in metrics) / len(metrics) if metrics else 0.0
        agg_precision = (
            sum(m.metrics.precision for m in metrics) / len(metrics) if metrics else 0.0
        )

        result = EvalSplitOutput(
            split=payload.split,
            detailed_metrics=None,
            specimens=None,
            aggregate_recall=agg_recall,
            aggregate_precision=agg_precision,
            specimen_count=len(metrics),
            issue_count=sum(m.metrics.expected for m in metrics),
            cost=cost,
            total_cost_so_far=state.total_cost,
            budget_remaining=budget_remaining,
            eval_dir=_translate_host_path(eval_dir),
        )
        (eval_dir / "valid_summary.json").write_text(
            result.model_dump_json(indent=2), encoding="utf-8"
        )
        return result

    @mcp.tool(flat=True)
    async def eval_specimen(payload: EvalSpecimenInput) -> EvalSpecimenOutput:
        """Evaluate a prompt on one specimen (medium cost, ~$1-5)."""
        # Read prompt from file (translate container path to host path)
        prompt_text = _read_prompt_file(payload.prompt_path)

        # Budget check before starting work
        state.check_budget_before_work()

        # Create eval directory
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        eval_dir = evals_dir / f"eval_{ts}"
        eval_dir.mkdir(parents=True, exist_ok=True)
        (eval_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")
        logger.info("eval_specimen %s: %s", payload.specimen, eval_dir)

        # Run critic + grader on specimen
        out_dir = eval_dir / payload.specimen
        out_dir.mkdir(parents=True, exist_ok=True)

        # Set up cost tracking (no RichDisplayHandler here - created inside with servers)
        cost_tracker = CostTrackingHandler()
        extra_handlers = (cost_tracker,)

        # Run critic
        critic_obj = await _run_critic_for_specimen(
            payload.specimen,
            prompt_text,
            client,
            eval_dir,
            agent_model=agent_model,
            extra_handlers=extra_handlers,
            verbose=state.verbose,
            verbose_prefix=f"  [{payload.specimen}] ",
        )
        critic_cost = cost_tracker.total_cost

        # Reset for grader
        cost_tracker.total_cost = 0.0

        # Run grader
        grade_obj = await grade_critic_output(
            payload.specimen,
            critic_obj,
            client,
            transcript_out_dir=out_dir,
            extra_handlers=extra_handlers,
            verbose=state.verbose,
            verbose_prefix=f"  [{payload.specimen}] ",
        )
        grader_cost = cost_tracker.total_cost

        (out_dir / "grade.json").write_text(
            grade_obj.model_dump_json(indent=2), encoding="utf-8"
        )

        # Calculate cost
        cost = critic_cost + grader_cost
        state.total_cost += cost

        # Construct output with nested GradeMetrics
        return EvalSpecimenOutput(
            specimen=payload.specimen,
            metrics=grade_obj.metrics,
            cost=cost,
            eval_dir=_translate_host_path(eval_dir),
        )

    @mcp.tool(flat=True)
    async def eval_file(payload: EvalFileInput) -> EvalFileOutput:
        """Evaluate a prompt on one file (fast iteration, low cost ~$0.10-0.50)."""
        # Read prompt from file (translate container path to host path)
        prompt_text = _read_prompt_file(payload.prompt_path)

        # Budget check before starting work
        state.check_budget_before_work()

        # Create eval directory
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        eval_dir = evals_dir / f"eval_{ts}"
        eval_dir.mkdir(parents=True, exist_ok=True)
        (eval_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")
        logger.info(
            "eval_file %s:%s: %s", payload.specimen, payload.file_path, eval_dir
        )

        # Run per-file eval with file filter (cost tracked internally)
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

        # Extract results for the single file
        if not result.per_file_runs:
            raise RuntimeError(f"No results returned for file {payload.file_path}")

        file_result = result.per_file_runs[0]  # Only one file since we filtered
        detected_ids = file_result.detected_issue_ids

        return EvalFileOutput(
            specimen=payload.specimen,
            file_path=payload.file_path,
            issues_in_file=file_result.issues_in_file,
            detected_issues=detected_ids,
            detection_rate=(
                len(detected_ids) / len(file_result.issues_in_file)
                if file_result.issues_in_file
                else 0.0
            ),
            cost=cost,
            eval_dir=_translate_host_path(eval_dir),
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

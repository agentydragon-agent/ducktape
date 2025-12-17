"""Main orchestrator for agent-based prompt improvement workflow.

Creates a scoped database environment, mounts training snapshot code, and runs
an improvement agent with token budget enforcement and prompt submission.

The agent queries the database on-demand rather than receiving pre-loaded trajectories,
enabling evaluation of 10-50 examples (vs GEPA's 3-5) with lower context consumption.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
import hashlib
import logging
from pathlib import Path
import tempfile
from typing import Annotated, Literal
from uuid import UUID, uuid4

import aiodocker
from fastmcp.client import Client
from pydantic import BaseModel, Field

from adgn.agent.agent import Agent
from adgn.agent.bootstrap import TypedBootstrapBuilder, read_package_file_call
from adgn.agent.handler import AbortIf, RedirectOnTextMessageHandler, SequenceHandler
from adgn.agent.loop_control import AllowAnyToolOrTextMessage, InjectItems
from adgn.mcp._shared.container_session import BindMount
from adgn.mcp._shared.mounted import Mounted
from adgn.mcp.exec.docker.server import ContainerExecServer
from adgn.openai_utils.client_factory import build_client
from adgn.openai_utils.model import FunctionCallItem, SystemMessage, UserMessage
from adgn.props.agent_setup import build_props_handlers
from adgn.props.db.config import DatabaseConfig
from adgn.props.docker_env import PROPS_NETWORK_NAME, PropertiesDockerCompositor
from adgn.props.hydration import SnapshotHydrator, SnapshotSlug
from adgn.props.prompt_improve.prompt_submission_server import (
    ExampleInfo,
    ImprovementContext,
    PromptSubmission,
    PromptSubmissionServer,
)
from adgn.props.prompt_improve.token_budget_handler import TokenBudgetHandler
from adgn.props.prompt_improve.user_manager import ImprovementUserManager
from adgn.props.prompts.util import render_prompt_template
from adgn.props.snapshot_paths import snapshot_container_path

logger = logging.getLogger(__name__)


class OutcomeSuccess(BaseModel):
    """Agent successfully submitted an improved prompt."""

    kind: Literal["success"] = "success"
    submission: PromptSubmission


class OutcomeExhausted(BaseModel):
    """Agent exhausted token budget without submission."""

    kind: Literal["exhausted"] = "exhausted"


class OutcomeUnexpectedTermination(BaseModel):
    """Agent terminated without submission or exhaustion (unexpected)."""

    kind: Literal["unexpected_termination"] = "unexpected_termination"
    message: str


ImprovementOutcome = Annotated[
    OutcomeSuccess | OutcomeExhausted | OutcomeUnexpectedTermination, Field(discriminator="kind")
]


class ImprovementResult(BaseModel):
    """Result from running improvement agent with common fields and outcome."""

    tokens_used: int
    run_id: UUID
    outcome: ImprovementOutcome


# ============================================================================
# Bootstrap Helpers
# ============================================================================


def _read_package_files(
    builder: TypedBootstrapBuilder, runtime: Mounted[ContainerExecServer], package: str, files: list[str]
) -> list[FunctionCallItem]:
    """Helper to generate multiple read_package_file_call invocations."""
    return [read_package_file_call(builder, runtime, package, f) for f in files]


def make_improvement_bootstrap_calls(
    builder: TypedBootstrapBuilder,
    resources: Mounted,
    runtime: Mounted[ContainerExecServer],
    prompt_submission: Mounted,
) -> list[FunctionCallItem]:
    """Build bootstrap calls: improvement context and database query examples.

    Provides:
    - Improvement context resource (example info, current prompt SHA)
    - SQL query examples for analyzing critic runs, grader results, execution traces

    Args:
        builder: Bootstrap builder for generating typed tool calls
        resources: Mounted resources server (comp.resources)
        runtime: Mounted runtime server for reading package files
        prompt_submission: Mounted prompt submission server
    """
    return [
        # System overview (snapshots, database, critic architecture, evaluation flow)
        *_read_package_files(builder, runtime, "adgn.props.docs", ["system_overview.md"]),
        # Improvement context (examples, current prompt SHA)
        builder.read_resource(
            resources,
            server=prompt_submission.prefix,
            uri=prompt_submission.server.improvement_context_resource.uri,
            max_bytes=4096,
        ),
        # Database query examples for analyzing training data
        *_read_package_files(
            builder,
            runtime,
            "adgn.props.examples",
            [
                "working_with_examples.py",  # Example schema (composite key pattern)
                "analyzing_critic_failures.py",  # Critic runs, grader results, execution traces
                "query_run_status.py",  # Check for stuck/looping behavior (max_turns_exceeded)
            ],
        ),
    ]


async def run_improvement_agent(
    examples: list[
        tuple[SnapshotSlug, str | None]
    ],  # [(snapshot_slug, scope_hash), ...] - scope_hash is None for whole-snapshot
    current_prompt: str,
    token_budget: int,
    model: str,
    hydrator: SnapshotHydrator,
    docker_client: aiodocker.Docker,
    db_config: DatabaseConfig,
    output_dir: Path | None = None,
    verbose: bool = False,
) -> ImprovementResult:
    """Run improvement agent on N training examples.

    Creates a temporary PostgreSQL user with RLS-scoped access to only the specified
    training examples. Hydrates and mounts snapshot code at /snapshots/{slug}/.
    Runs agent with token budget enforcement and prompt submission MCP server.

    Args:
        examples: List of (snapshot_slug, scope_hash) tuples to analyze
        current_prompt: Baseline prompt being improved
        token_budget: Maximum tokens (e.g., 200_000)
        model: LLM model for improvement agent (e.g., "o1-mini")
        hydrator: Snapshot hydrator (required)
        docker_client: Docker client (required)
        db_config: Database configuration (required, from CLI caller)
        output_dir: Output directory for workspace/logs (defaults to temp)
        verbose: Enable verbose logging

    Returns:
        ImprovementResult with submission (if any), token usage, status

    Example:
        result = await run_improvement_agent(
            examples=[("ducktape/2025-11-20-00", "abc123"), ...],
            current_prompt="You are a code reviewer...",
            token_budget=200_000,
            model="o1-mini",
        )

        if isinstance(result.outcome, OutcomeSuccess):
            logger.info(f"Submitted: {result.outcome.submission.prompt_text[:100]}...")
            logger.info(f"Tokens: {result.tokens_used:,}")
    """
    if not examples:
        raise ValueError("examples must not be empty")

    run_id = uuid4()

    # Default arguments
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix=f"improve_agent_{str(run_id)[:8]}_"))

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        f"Starting improvement agent run {run_id}: "
        f"{len(examples)} examples, {token_budget:,} token budget, model={model}"
    )
    logger.info(f"Output directory: {output_dir}")

    # Filter out examples with None scope_hash (should not happen, but type-safe)
    valid_examples: list[tuple[SnapshotSlug, str]] = [(slug, h) for slug, h in examples if h is not None]
    if len(valid_examples) != len(examples):
        logger.warning(f"Filtered out {len(examples) - len(valid_examples)} examples with None scope_hash")
    if not valid_examples:
        raise ValueError("No valid examples after filtering None scope_hash values")

    # TODO: Migrate to HTTP mode with AgentEnvironment abstraction (like critic/grader)
    # - Create ImprovementAgentEnvironment extending AgentEnvironment
    # - Move user management and compositor setup to base class
    # - Would simplify lifecycle management and improve consistency with other agents
    # - Consider HTTP transport for any submit/finalization tools

    # 1. Create scoped database user with RLS policies
    async with ImprovementUserManager(db_config.admin, run_id, valid_examples) as creds:
        # Container-to-container database access with scoped user credentials
        agent_db_container = db_config.for_container_user(creds)

        # 2. Hydrate snapshots and keep alive for Docker mounting
        unique_slugs = sorted({SnapshotSlug(slug) for slug, _ in examples})
        snapshot_paths: dict[SnapshotSlug, Path] = {}

        logger.info(f"Hydrating {len(unique_slugs)} unique snapshots")

        async with AsyncExitStack() as stack:
            # Hydrate each snapshot
            for slug in unique_slugs:
                hydrated = await stack.enter_async_context(hydrator.hydrate(slug))
                snapshot_paths[slug] = hydrated.content_root
                logger.debug(f"Hydrated {slug} → {hydrated.content_root}")

            # 3. Build Docker bind mounts
            # Snapshot source code (ro) - mount each separately without split in path
            # Agents should NOT know which split (train/valid/test) they're working on
            extra_binds = [
                BindMount(host_path=path.resolve(), container_path=snapshot_container_path(slug), mode="ro")
                for slug, path in snapshot_paths.items()
            ]

            logger.info(f"Mounted {len(extra_binds)} snapshots (read-only)")

            # 4. Create compositor with MCP servers
            async with PropertiesDockerCompositor(
                workspace_root=output_dir,
                docker_client=docker_client,
                mount_properties=False,  # Agent doesn't need property definitions
                hydrator=hydrator,
                extra_binds=extra_binds,
                ephemeral=False,  # Keep container for debugging if needed
                workspace_mode="rw",  # Agent writes improved prompt here
                db_conn=agent_db_container,  # Scoped database access
                network_mode=PROPS_NETWORK_NAME,  # For database access
            ) as comp:
                # Build improvement context with example information (use valid_examples with non-None scope_hash)
                improvement_ctx = ImprovementContext(
                    examples=[ExampleInfo(snapshot_slug=slug, scope_hash=fhash) for slug, fhash in valid_examples],
                    current_prompt_sha256=hashlib.sha256(current_prompt.encode()).hexdigest(),
                )

                # Mount prompt submission server
                prompt_submission_server = PromptSubmissionServer(
                    workspace_root=output_dir, improvement_context=improvement_ctx
                )
                prompt_submission = await comp.mount_inproc("prompt_submission", prompt_submission_server)

                # 5. Set up handlers
                token_handler = TokenBudgetHandler(max_tokens=token_budget)

                # Bootstrap calls (inject improvement context and database query examples)
                builder = TypedBootstrapBuilder.for_server(prompt_submission.server)
                bootstrap_calls = make_improvement_bootstrap_calls(
                    builder, comp.resources, comp.runtime, prompt_submission
                )
                bootstrap = SequenceHandler([InjectItems(items=bootstrap_calls)])

                # Compose all handlers
                props_handlers = await build_props_handlers(
                    transcript_id=run_id,
                    verbose_prefix=f"[IMPROVE {str(run_id)[:8]}] " if verbose else None,
                    compositor=comp,
                )
                handlers = [
                    bootstrap,
                    *props_handlers,
                    RedirectOnTextMessageHandler(
                        reminder_message=(
                            "You are a prompt improvement agent. Your improved prompt has not yet been submitted "
                            "(prompt_submission_submit_prompt tool has not been called), so your task is unfinished. "
                            "Analyze the provided training examples by querying the database, identify failure patterns, "
                            "design improvements to the critic prompt, write the improved prompt to /workspace/improved-prompt.md "
                            "using docker_exec, then submit it via the prompt_submission_submit_prompt MCP tool. "
                            "This is not an interactive workflow with a user - you must complete the analysis and "
                            "submit the improved prompt via MCP tools, not via text messages asking for confirmation. "
                            "Do not ask 'if you want, I can...' - just execute your plan and submit the result."
                        )
                    ),
                    AbortIf(should_abort=lambda: prompt_submission_server.get_submission() is not None),
                    token_handler,
                ]

                # 6. System prompt
                system_prompt = _render_improvement_prompt(
                    current_prompt=current_prompt, examples=examples, output_dir=output_dir
                )

                # 7. Create and run agent
                client = build_client(model)

                async with Client(comp) as mcp_client:
                    agent = await Agent.create(
                        mcp_client=mcp_client,
                        client=client,
                        handlers=handlers,
                        parallel_tool_calls=True,
                        tool_policy=AllowAnyToolOrTextMessage(),
                    )

                    # System prompt
                    agent.insert_message(SystemMessage.text(system_prompt))

                    # Initial user message
                    agent.insert_message(
                        UserMessage.text(
                            f"Analyze {len(examples)} training examples and propose an improved "
                            "critic prompt. Focus on identifying failure patterns and designing "
                            "targeted improvements to the prompt."
                        )
                    )

                    logger.info("Starting agent loop")
                    await agent.run()
                    logger.info("Agent loop completed")

                # 8. Construct result based on final state
                tokens_used = token_handler.cumulative_tokens
                submission = prompt_submission_server.get_submission()

                outcome: ImprovementOutcome
                if submission is not None:
                    outcome = OutcomeSuccess(submission=submission)
                elif token_handler.percentage_used >= 1.0:
                    outcome = OutcomeExhausted()
                else:
                    outcome = OutcomeUnexpectedTermination(
                        message=f"Agent terminated with {token_handler.percentage_used:.1%} "
                        f"budget used without submission or exhaustion"
                    )

                result = ImprovementResult(tokens_used=tokens_used, run_id=run_id, outcome=outcome)

                # TODO: Store improvement result in database (similar to CriticRun/GraderRun tables)
                # Consider adding an ImprovementRun table with:
                # - run_id (UUID, PK)
                # - examples (JSONB: list of (snapshot_slug, scope_hash) tuples)
                # - current_prompt_sha256 (TEXT)
                # - outcome_kind (TEXT: success/exhausted/unexpected_termination)
                # - submission (JSONB: prompt_text, rationale, if submitted)
                # - tokens_used (INTEGER)
                # - model (TEXT)
                # - created_at (TIMESTAMP)
                # This enables querying improvement agent history, analyzing successful
                # improvements, and tracking prompt evolution over time.

                logger.info(
                    f"Improvement agent completed: kind={outcome.kind}, tokens={tokens_used:,}/{token_budget:,}"
                )

                return result


def _render_improvement_prompt(
    current_prompt: str, examples: list[tuple[SnapshotSlug, str | None]], output_dir: Path
) -> str:
    """Render system prompt for improvement agent from template."""
    snapshot_slugs = sorted({slug for slug, _ in examples})

    return render_prompt_template(
        "prompt_improve/prompts/improvement_agent_system.j2.md",
        current_prompt=current_prompt,
        n_examples=len(examples),
        snapshot_slugs=snapshot_slugs,
    )

"""Main orchestrator for agent-based prompt improvement workflow.

Creates a scoped database environment, mounts training snapshot code, and runs
an improvement agent with token budget enforcement and prompt submission.

The agent queries the database on-demand rather than receiving pre-loaded trajectories,
enabling evaluation of 10-50 examples (vs GEPA's 3-5) with lower context consumption.
"""

from __future__ import annotations

from collections.abc import Sequence
import hashlib
import logging
from pathlib import Path
import tempfile
from typing import Annotated, Literal
from uuid import UUID, uuid4

import aiodocker
from fastmcp.client import Client
from fastmcp.server.auth import AuthProvider
from pydantic import BaseModel, Field

from adgn.agent.agent import Agent
from adgn.agent.bootstrap import TypedBootstrapBuilder, read_package_files_call
from adgn.agent.handler import AbortIf, RedirectOnTextMessageHandler, SequenceHandler
from adgn.agent.loop_control import AllowAnyToolOrTextMessage, InjectItems
from adgn.mcp._shared.mounted import Mounted
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.mcp.exec.docker.server import ContainerExecServer
from adgn.openai_utils.model import OpenAIModelProto, SystemMessage, UserMessage
from adgn.props.agent_setup import AgentEnvironment, build_props_handlers, make_mcp_http_bootstrap_calls
from adgn.props.db.config import DatabaseConfig
from adgn.props.hydration import SnapshotHydrator, SnapshotSlug
from adgn.props.prompt_improve.prompt_submission_server import (
    IMPROVEMENT_CONTEXT_RESOURCE_URI,
    ExampleInfo,
    ImprovementContext,
    PromptSubmission,
    PromptSubmissionServer,
)
from adgn.props.prompt_improve.token_budget_handler import TokenBudgetHandler
from adgn.props.prompt_improve.user_manager import ImprovementUserManager
from adgn.props.prompts.util import render_prompt_template

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
# Agent Environment
# ============================================================================


class ImprovementAgentEnvironment(AgentEnvironment):
    """Agent environment for prompt improvement with prompt_submission MCP server.

    Provides complete environment for improvement agents:
    - Temporary database user with RLS scoping (improvement_agent_{run_id})
    - HTTP MCP server with prompt_submission tool
    - Docker container with docker_exec
    - Train snapshots mounted at /snapshots/<slug>/
    - Workspace mounted read-write at /workspace/ for prompt files

    Agent workflow:
    1. Queries database for critic runs, grader results, execution traces
    2. Analyzes failures on specific training examples
    3. Writes improved prompt to /workspace/
    4. Calls prompt_submission tool via MCP-over-HTTP when done

    Usage:
        async with ImprovementAgentEnvironment(
            workspace_root=Path("/workspace"),
            docker_client=docker_client,
            hydrator=hydrator,
            improvement_run_id=uuid4(),
            allowed_examples=[(slug, scope_hash), ...],
            improvement_context=ImprovementContext(...),
            db_config=config,
            snapshot_slugs=[...],
        ) as compositor:
            # Run improvement agent
            ...
    """

    # Exposed for accessing server resources programmatically
    prompt_submission_server: PromptSubmissionServer

    def __init__(
        self,
        workspace_root: Path,
        docker_client: aiodocker.Docker,
        hydrator: SnapshotHydrator,
        improvement_run_id: UUID,
        allowed_examples: list[tuple[SnapshotSlug, str]],
        improvement_context: ImprovementContext,
        db_config: DatabaseConfig,
        snapshot_slugs: Sequence[SnapshotSlug] = (),
    ):
        """Create improvement agent environment.

        Args:
            workspace_root: Path to workspace directory (mounted read-write at /workspace/)
            docker_client: Async Docker client
            hydrator: Snapshot hydrator
            improvement_run_id: UUID of the improvement run (for RLS scoping)
            allowed_examples: List of (snapshot_slug, scope_hash) tuples agent can access
            improvement_context: Improvement context with example info, current prompt SHA
            db_config: Database configuration (passed via DI)
            snapshot_slugs: Train snapshots to hydrate and mount
        """
        # Store parameters for server factory and external access
        self._improvement_context = improvement_context
        self._workspace_root = workspace_root
        self._improvement_run_id = improvement_run_id

        def make_user_manager() -> ImprovementUserManager:
            """Create temporary improvement user with RLS scoping.

            The user manager handles run registration internally.
            """
            return ImprovementUserManager(db_config.admin, improvement_run_id, allowed_examples)

        super().__init__(
            docker_client=docker_client,
            user_manager_factory=make_user_manager,
            hydrator=hydrator,
            db_config=db_config,
            snapshot_slugs=snapshot_slugs,
            workspace_root=workspace_root,  # Use provided workspace (not temporary)
            mount_properties=False,
        )

    @property
    def improvement_run_id(self) -> UUID:
        """Get the improvement run ID for provenance tracking.

        Use this when upserting prompts to link them to this run.

        TODO: When improvement agent can run small evals, automatically link
        prompts to the run during upsert.
        """
        return self._improvement_run_id

    def bootstrap_mcp_resources(self) -> Sequence[tuple[str, str]]:
        """Return list of (label, URI) tuples for MCP resources to read during bootstrap.

        Returns:
            List of (label, URI) pairs for improvement agent resources
        """
        return [("Improvement Context", IMPROVEMENT_CONTEXT_RESOURCE_URI)]

    def bootstrap_items(self, builder: TypedBootstrapBuilder, runtime: Mounted[ContainerExecServer]) -> list:
        """Build bootstrap items for improvement agent initialization.

        Includes:
        - Improvement context resource (via MCP-over-HTTP bootstrap script)
        - System overview (dataset structure, evaluation flow)
        - Database query examples for analyzing critic runs, grader results, execution traces

        Args:
            builder: Bootstrap builder for generating typed tool calls
            runtime: Mounted runtime server (comp.runtime)

        Returns:
            List of FunctionCallItems to inject before agent sampling
        """
        return [
            # MCP-over-HTTP bootstrap (lists tools, reads resources)
            *make_mcp_http_bootstrap_calls(builder, runtime, self.bootstrap_mcp_resources()),
            # All package file reads (single call for efficiency)
            read_package_files_call(
                builder,
                runtime,
                [
                    # Database ORM models (single source of truth for schema)
                    ("adgn.props.db", ["models.py"]),
                    # System overview (snapshots, database, critic architecture, evaluation flow)
                    ("adgn.props.docs", ["system_overview.md"]),
                    # Shared examples (database queries, run analysis)
                    ("adgn.props.examples", ["working_with_examples.py", "runs.py"]),
                ],
            ),
        ]

    def _make_mcp_server(self, auth: AuthProvider) -> EnhancedFastMCP:
        """Create prompt submission server.

        Args:
            auth: Auth provider for HTTP authentication (unused - server doesn't use auth)

        Returns:
            PromptSubmissionServer with prompt submission tools
        """
        # Type narrowing: _workspace_root is guaranteed non-null (passed to __init__)
        assert self._workspace_root is not None, "workspace_root must be set"
        server = PromptSubmissionServer(
            workspace_root=self._workspace_root, improvement_context=self._improvement_context
        )
        # Store reference for programmatic access (bootstrap introspection)
        self.prompt_submission_server = server
        return server


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
    client: OpenAIModelProto,
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
        client: OpenAI client (required, allows testing with mocks)
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

    # Build improvement context with example information (use valid_examples with non-None scope_hash)
    improvement_ctx = ImprovementContext(
        examples=[ExampleInfo(snapshot_slug=slug, scope_hash=fhash) for slug, fhash in valid_examples],
        current_prompt_sha256=hashlib.sha256(current_prompt.encode()).hexdigest(),
    )

    # Get unique snapshots for mounting
    unique_slugs = sorted({SnapshotSlug(slug) for slug, _ in examples})
    logger.info(f"Will mount {len(unique_slugs)} unique snapshot(s) (environment will handle hydration)")

    # Create agent environment with prompt submission HTTP MCP server and temporary user
    # workspace_root (output_dir) will be mounted as /workspace (rw mode for agent to write prompts)
    # AgentEnvironment creates temporary database user with RLS-scoped access to allowed_examples
    # AgentEnvironment handles snapshot hydration, HTTP server, and container lifecycle
    agent_env = ImprovementAgentEnvironment(
        workspace_root=output_dir,
        docker_client=docker_client,
        hydrator=hydrator,
        improvement_run_id=run_id,
        allowed_examples=valid_examples,
        improvement_context=improvement_ctx,
        db_config=db_config,
        snapshot_slugs=unique_slugs,  # AgentEnvironment will hydrate and mount these automatically
    )

    async with agent_env as comp:
        # comp is a PropertiesDockerCompositor with:
        # - comp.runtime (Docker exec server)
        # - HTTP MCP server with prompt_submission tool (accessed via MCP client)

        # Set up handlers
        token_handler = TokenBudgetHandler(max_tokens=token_budget)

        # Bootstrap calls using agent environment's bootstrap method
        builder = TypedBootstrapBuilder.for_server(agent_env.prompt_submission_server)
        logger.info("Improvement agent bootstrap: using agent environment bootstrap items")
        bootstrap_calls = agent_env.bootstrap_items(builder, comp.runtime)
        bootstrap = SequenceHandler([InjectItems(items=bootstrap_calls)])

        # Compose all handlers
        props_handlers = await build_props_handlers(
            transcript_id=run_id, verbose_prefix=f"[IMPROVE {str(run_id)[:8]}] " if verbose else None, compositor=comp
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
            AbortIf(should_abort=lambda: agent_env.prompt_submission_server.get_submission() is not None),
            token_handler,
        ]

        # System prompt
        system_prompt = _render_improvement_prompt(
            current_prompt=current_prompt, examples=examples, output_dir=output_dir
        )

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

        # Construct result based on final state
        tokens_used = token_handler.cumulative_tokens
        submission = agent_env.prompt_submission_server.get_submission()

        outcome: ImprovementOutcome
        if submission is not None:
            # Upsert submitted prompt with provenance tracking
            from adgn.props.db.prompts import hash_and_upsert_prompt

            prompt_sha = hash_and_upsert_prompt(
                prompt_text=submission.prompt_text, improvement_run_id=agent_env.improvement_run_id
            )
            logger.info(f"Upserted improved prompt {prompt_sha[:12]}... with improvement_run_id={run_id}")
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

        logger.info(f"Improvement agent completed: kind={outcome.kind}, tokens={tokens_used:,}/{token_budget:,}")

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

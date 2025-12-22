"""Main orchestrator for agent-based prompt improvement workflow.

Creates a scoped database environment, mounts training snapshot code, and runs
an improvement agent with token budget enforcement and prompt submission.

The agent queries the database on-demand rather than receiving pre-loaded trajectories,
enabling evaluation of 10-50 examples (vs GEPA's 3-5) with lower context consumption.
"""

from __future__ import annotations

from collections.abc import Sequence
import logging
from pathlib import Path
import tempfile
from typing import Annotated, Literal
from uuid import UUID, uuid4

import aiodocker
from fastmcp.client import Client
from fastmcp.server.auth import AuthProvider
from pydantic import BaseModel, Field

from adgn.agent.display import CompactDisplayHandler
from adgn.agent.handler import AbortIf
from adgn.agent.turn_limit import MaxTurnsHandler
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.openai_utils.model import OpenAIModelProto, UserMessage
from adgn.props.agent_handle import AgentHandle
from adgn.props.agent_setup import AgentEnvironment
from adgn.props.agent_types import AllowedExample, ImprovementTypeConfig
from adgn.props.agent_workspace import WorkspaceManager
from adgn.props.cli.common_options import DEFAULT_MAX_LINES
from adgn.props.db import get_session
from adgn.props.db.agent_definition_ids import IMPROVEMENT_AGENT_DEFINITION_ID
from adgn.props.db.config import DatabaseConfig
from adgn.props.db.models import AgentRun, AgentRunStatus
from adgn.props.hydration import SnapshotHydrator, SnapshotSlug
from adgn.props.prompt_improve.reminder_handler import ImprovementReminderHandler
from adgn.props.prompt_improve.token_budget_handler import TokenBudgetHandler
from adgn.props.prompt_optimize.prompt_optimizer import PromptEvalServer, PromptOptimizerState
from adgn.props.prompt_optimize.target_metric import TargetMetric

logger = logging.getLogger(__name__)


class OutcomeSuccess(BaseModel):
    """Agent successfully created improved definition(s) that beat baseline."""

    kind: Literal["success"] = "success"
    definition_id: str = Field(description="ID of the definition that beat the baseline average")
    issues_found: float = Field(description="Total issues found by this definition on allowed_examples")
    baseline_avg: float = Field(description="Average issues found by baseline definitions")


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
    """Agent environment for prompt improvement with evaluation MCP server.

    Provides complete environment for improvement agents:
    - Temporary database user with RLS scoping (improvement_agent_{run_id})
    - HTTP MCP server with evaluation tools (create_critic_definition, run_critic, run_grader)
    - Docker container with docker_exec
    - Train snapshots mounted at /snapshots/<slug>/
    - Workspace mounted read-write at /workspace/ for definition files

    Agent workflow:
    1. Queries database for critic runs, grader results, execution traces
    2. Queries own agent_runs row for baseline_definition_ids and allowed_examples
    3. Analyzes failures on specific training examples
    4. Creates improved definition directory at /workspace/improved/
    5. Calls create_critic_definition tool to store definition
    6. Runs evals via run_critic and run_grader tools
    7. Iterates until definition beats baseline average (termination via ImprovementReminderHandler)

    Usage:
        async with ImprovementAgentEnvironment(
            docker_client=docker_client,
            hydrator=hydrator,
            improvement_run_id=uuid4(),
            baseline_definition_ids=[...],
            allowed_examples=[...],
            critic_client=critic_client,
            grader_client=grader_client,
            db_config=config,
            workspace_manager=WorkspaceManager.from_env(),
            snapshot_slugs=[...],
        ) as compositor:
            # Run improvement agent
            ...
    """

    # Exposed for accessing server resources programmatically
    prompt_eval_server: PromptEvalServer
    agent_state: PromptOptimizerState

    def __init__(
        self,
        docker_client: aiodocker.Docker,
        hydrator: SnapshotHydrator,
        improvement_run_id: UUID,
        baseline_definition_ids: list[str],
        allowed_examples: list[AllowedExample],
        critic_client: OpenAIModelProto,
        grader_client: OpenAIModelProto,
        db_config: DatabaseConfig,
        workspace_manager: WorkspaceManager,
        snapshot_slugs: Sequence[SnapshotSlug] = (),
        verbose: bool = False,
    ):
        """Create improvement agent environment.

        Args:
            docker_client: Async Docker client
            hydrator: Snapshot hydrator
            improvement_run_id: UUID of the improvement run (for RLS scoping)
            baseline_definition_ids: Agent definition IDs to study and improve
            allowed_examples: List of AllowedExample specifying which examples agent can access
            critic_client: OpenAI client for running critic evaluations
            grader_client: OpenAI client for running grader evaluations
            db_config: Database configuration (passed via DI)
            workspace_manager: Workspace manager for agent directories
            snapshot_slugs: Train snapshots to hydrate and mount
            verbose: Enable verbose output
        """
        # Build type_config with allowed_examples for RLS
        type_config = ImprovementTypeConfig(
            baseline_definition_ids=baseline_definition_ids, allowed_examples=allowed_examples
        )
        self._type_config = type_config

        # Store clients for server factory
        self._critic_client = critic_client
        self._grader_client = grader_client
        self._verbose = verbose

        # State for report_failure tool (shared with prompt optimizer server)
        self.agent_state = PromptOptimizerState()

        super().__init__(
            definition_id=IMPROVEMENT_AGENT_DEFINITION_ID,
            agent_run_id=improvement_run_id,
            docker_client=docker_client,
            hydrator=hydrator,
            db_config=db_config,
            workspace_manager=workspace_manager,
            snapshot_slugs=snapshot_slugs,
        )

    @property
    def type_config(self) -> ImprovementTypeConfig:
        """Get the type config for creating the AgentRun record."""
        return self._type_config

    def _make_mcp_server(self, auth: AuthProvider) -> EnhancedFastMCP:
        """Create evaluation server with critic/grader tools.

        Args:
            auth: Auth provider for HTTP authentication (unused - server doesn't use auth)

        Returns:
            PromptEvalServer with evaluation tools (create_critic_definition, run_critic, run_grader)
        """
        server = PromptEvalServer(
            critic_client=self._critic_client,
            grader_client=self._grader_client,
            docker_client=self._docker_client,
            hydrator=self._hydrator,
            db_config=self._db_config,
            workspace_manager=self._workspace_manager,
            optimizer_state=self.agent_state,
            target_metric=TargetMetric.TARGETED,  # Improvement agent uses targeted mode (sees all examples)
            optimizer_run_id=self.agent_run_id,
            workspace_root=self.workspace_root,
            budget_limit=float("inf"),  # No budget limit for improvement agent (uses token budget instead)
            verbose=self._verbose,
        )
        # Store reference for programmatic access (bootstrap introspection)
        self.prompt_eval_server = server
        return server


async def run_improvement_agent(
    examples: list[AllowedExample],
    baseline_definition_ids: list[str],
    token_budget: int,
    model: str,
    hydrator: SnapshotHydrator,
    docker_client: aiodocker.Docker,
    db_config: DatabaseConfig,
    client: OpenAIModelProto,
    critic_client: OpenAIModelProto,
    grader_client: OpenAIModelProto,
    output_dir: Path | None = None,
    verbose: bool = False,
) -> ImprovementResult:
    """Run improvement agent on N training examples.

    Creates a temporary PostgreSQL user with RLS-scoped access to TRAIN split data.
    Hydrates and mounts snapshot code at /snapshots/{slug}/.
    Runs agent with token budget enforcement and evaluation MCP server.

    Termination condition: Agent has created a definition that beats the average
    of baseline definitions on total issues found across all allowed_examples.

    Args:
        examples: List of AllowedExample (snapshot_slug, scope_hash) to analyze
        baseline_definition_ids: Agent definition IDs to study and improve
        token_budget: Maximum tokens (e.g., 200_000)
        model: LLM model for improvement agent (e.g., "o1-mini")
        hydrator: Snapshot hydrator (required)
        docker_client: Docker client (required)
        db_config: Database configuration (required, from CLI caller)
        client: OpenAI client for the improvement agent itself
        critic_client: OpenAI client for running critic evaluations
        grader_client: OpenAI client for running grader evaluations
        output_dir: Output directory for workspace/logs (defaults to temp)
        verbose: Enable verbose logging

    Returns:
        ImprovementResult with outcome (success if beat baseline, exhausted if budget exceeded)

    Example:
        result = await run_improvement_agent(
            examples=[AllowedExample(snapshot_slug="ducktape/2025-11-20-00", scope_hash="abc123")],
            baseline_definition_ids=["critic-v1"],
            token_budget=200_000,
            model="o1-mini",
            critic_client=critic_client,
            grader_client=grader_client,
        )

        if isinstance(result.outcome, OutcomeSuccess):
            logger.info(f"Agent beat baseline average!")
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

    # Get unique snapshots for mounting
    unique_slugs = sorted({SnapshotSlug(ex.snapshot_slug) for ex in examples})
    logger.info(f"Will mount {len(unique_slugs)} unique snapshot(s) (environment will handle hydration)")

    # Build type_config for AgentRun (same as used by ImprovementAgentEnvironment)
    type_config = ImprovementTypeConfig(baseline_definition_ids=baseline_definition_ids, allowed_examples=examples)

    # Phase 1: Write initial AgentRun to DB (BEFORE agent runs - FK constraint!)
    with get_session() as session:
        agent_run = AgentRun(
            agent_run_id=run_id,
            agent_definition_id=IMPROVEMENT_AGENT_DEFINITION_ID,
            model=model,
            type_config=type_config,
            status=AgentRunStatus.IN_PROGRESS,
        )
        session.add(agent_run)
        session.commit()
        logger.info(f"Created initial agent run in DB: agent_run_id={run_id}")

    # Create agent environment with evaluation MCP server and temporary user
    # AgentEnvironment creates temporary database user with RLS-scoped access to TRAIN data
    # AgentEnvironment handles snapshot hydration, HTTP server, and container lifecycle
    workspace_manager = WorkspaceManager.from_env()
    agent_env = ImprovementAgentEnvironment(
        docker_client=docker_client,
        hydrator=hydrator,
        improvement_run_id=run_id,
        baseline_definition_ids=baseline_definition_ids,
        allowed_examples=examples,
        critic_client=critic_client,
        grader_client=grader_client,
        db_config=db_config,
        workspace_manager=workspace_manager,
        snapshot_slugs=unique_slugs,  # AgentEnvironment will hydrate and mount these automatically
        verbose=verbose,
    )

    async with agent_env as comp:
        # comp is a PropertiesDockerCompositor with:
        # - comp.runtime (Docker exec server)
        # - HTTP MCP server with create_definition tool (accessed via MCP client)

        # Set up handlers
        token_handler = TokenBudgetHandler(max_tokens=token_budget)

        # Build handlers for improvement agent
        # NOTE: Do NOT call build_props_handlers() here - AgentHandle.create() already adds
        # DatabaseEventHandler. We only add CompactDisplayHandler if verbose is enabled.
        handlers: list = []
        if verbose:
            display_handler = await CompactDisplayHandler.from_compositor(
                comp, max_lines=DEFAULT_MAX_LINES, prefix=f"[IMPROVE {str(run_id)[:8]}] "
            )
            handlers.append(display_handler)

        # Create reminder handler that checks termination condition
        # (agent created a definition that beats baseline average on sum of issues)
        reminder_handler = ImprovementReminderHandler(
            improvement_run_id=run_id, type_config=type_config, db_config=db_config
        )

        handlers.extend(
            [
                reminder_handler,
                # Abort if agent called report_failure (treated same as prompt optimizer)
                AbortIf(should_abort=lambda: agent_env.agent_state.error is not None),
                token_handler,
                MaxTurnsHandler(max_turns=200),
            ]
        )

        async with Client(comp) as mcp_client:
            # Create agent handle - handles definition loading, workspace, init script
            handle = await AgentHandle.create(
                agent_run_id=run_id,
                definition_id=IMPROVEMENT_AGENT_DEFINITION_ID,
                model_client=client,
                mcp_client=mcp_client,
                compositor=comp,
                workspace_manager=workspace_manager,
                handlers=handlers,
                parallel_tool_calls=True,
            )

            # Initial user message
            handle.insert_message(
                UserMessage.text(
                    f"Analyze {len(examples)} training examples and propose an improved "
                    "critic agent definition. Focus on identifying failure patterns and designing "
                    "targeted improvements to the definition (AGENT.md prompt and init script)."
                )
            )

            logger.info("Starting agent loop")
            await handle.run()
            logger.info("Agent loop completed")

        # Construct result based on final state
        tokens_used = token_handler.cumulative_tokens
        termination_status = reminder_handler.last_status

        outcome: ImprovementOutcome
        if termination_status is not None and termination_status.should_terminate:
            # Agent created a definition that beats baseline average
            # Definition was stored in agent_definitions table by create_definition tool
            # with created_by_agent_run_id linking to this improvement run
            assert termination_status.best_candidate_id is not None
            assert termination_status.best_candidate_issues is not None
            assert termination_status.baseline_avg_issues is not None
            logger.info(
                f"Improvement succeeded: definition '{termination_status.best_candidate_id}' "
                f"with {termination_status.best_candidate_issues:.1f} issues "
                f"beats baseline avg {termination_status.baseline_avg_issues:.1f} (run_id={run_id})"
            )
            outcome = OutcomeSuccess(
                definition_id=termination_status.best_candidate_id,
                issues_found=termination_status.best_candidate_issues,
                baseline_avg=termination_status.baseline_avg_issues,
            )
        elif token_handler.percentage_used >= 1.0:
            outcome = OutcomeExhausted()
        elif agent_env.agent_state.error is not None:
            # Agent called report_failure
            outcome = OutcomeUnexpectedTermination(message=f"Agent reported failure: {agent_env.agent_state.error}")
        else:
            outcome = OutcomeUnexpectedTermination(
                message=f"Agent terminated with {token_handler.percentage_used:.1%} "
                f"budget used without beating baseline or exhaustion"
            )

        result = ImprovementResult(tokens_used=tokens_used, run_id=run_id, outcome=outcome)

        # Note: Improvement agent runs are tracked in unified agent_runs table via AgentRun
        # with ImprovementTypeConfig.allowed_examples in type_config JSONB column.
        # Definition provenance is tracked via agent_definitions.created_by_agent_run_id FK.

        logger.info(f"Improvement agent completed: kind={outcome.kind}, tokens={tokens_used:,}/{token_budget:,}")

        return result

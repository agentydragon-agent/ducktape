"""Prompt optimizer implementation.

Runs an LLM agent to optimize critic prompts using train/valid/test splits
with budget tracking and granular evaluation tools.

Includes MCP server for prompt evaluation (run_critic/run_grader tools).

DONE: Validate file selections match known scopes
- run_critic validates that selected files match a known scope exactly (order-independent)
- Scopes are pre-defined file sets from `critic_scopes.yaml` representing training datapoints
- This prevents arbitrary file selections and ensures meaningful ground truth coverage
- Grader raises error when grading critiques with 0 catchable TPs

DONE: Teach prompt optimizer about scopes
- System prompt explains scopes as "smaller datapoints" on a sub-snapshot scale
- SQL queries provided for listing scopes and grader runs per scope
- Related: See `docs/training_strategy.md` for per-file examples approach
"""

from collections.abc import Sequence
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import aiodocker
from fastmcp.client import Client
from fastmcp.exceptions import ToolError
from fastmcp.resources import FunctionResource
from fastmcp.tools import FunctionTool
from pydantic import Field

from adgn.agent.agent import Agent
from adgn.agent.bootstrap import TypedBootstrapBuilder, docker_exec_call_mounted, read_package_file_call
from adgn.agent.handler import AbortIf, RedirectOnTextMessageHandler, SequenceHandler
from adgn.agent.loop_control import AllowAnyToolOrTextMessage, InjectItems
from adgn.agent.turn_limit import MaxTurnsExceededError
from adgn.mcp._shared.constants import WORKING_DIR
from adgn.mcp._shared.container_session import BindMount, ContainerOptions
from adgn.mcp._shared.mounted import Mounted
from adgn.mcp._shared.types import MCPMountPrefix
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.mcp.exec.docker.server import ContainerExecServer
from adgn.mcp.resources.server import ResourcesServer
from adgn.openai_utils.model import FunctionCallItem, OpenAIModelProto, SystemMessage, UserMessage
from adgn.openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel
from adgn.openai_utils.types import ReasoningSummary
from adgn.props.agent_setup import build_props_handlers
from adgn.props.cli.common_options import DEFAULT_MAX_LINES
from adgn.props.critic.critic import run_critic as execute_critic_run
from adgn.props.critic.exceptions import CriticDidNotSubmitError, CriticExecutionError
from adgn.props.critic.models import CriticContextLengthExceeded, CriticInput, CriticMaxTurnsExceeded
from adgn.props.db import get_session
from adgn.props.db.config import DatabaseConfig, get_database_config
from adgn.props.db.models import CriticRun, Example, GraderRun as DBGraderRun, PromptOptimizationRun, Snapshot
from adgn.props.db.prompt_optimizer_user_manager import PromptOptimizerUserManager
from adgn.props.db.prompts import hash_and_upsert_prompt
from adgn.props.db.snapshots import DBGraderSuccess
from adgn.props.db.temp_user_manager import TempUserCredentials
from adgn.props.display import short_uuid
from adgn.props.docker_env import PROPS_NETWORK_NAME, PropertiesDockerCompositor
from adgn.props.files_hash import hash_file_set
from adgn.props.grader.exceptions import GraderDidNotSubmitError
from adgn.props.grader.grader import grade_critique_by_id
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import CriticScopeSpec, ExplicitFileScope
from adgn.props.prompt_optimize.budget_handler import BudgetEnforcementHandler
from adgn.props.prompts.util import render_prompt_template
from adgn.props.runs_context import RunsContext, format_timestamp_session
from adgn.props.splits import Split

from .target_metric import TargetMetric

logger = logging.getLogger(__name__)


# Common error message advice
_AGENT_STUCK_ADVICE = (
    "Agent exceeded turn limit. This could mean:\n"
    "  1. Agent needed more turns to complete the task (reading files, analyzing code, etc.)\n"
    "  2. Agent stuck in a loop or not following instructions\n"
    "  3. Agent ran out of tokens\n"
    "Check the transcript in the database to determine if the agent was making productive progress or stuck."
)

# Validation function name (SSOT for 'valid' split aggregate access in whole-repo mode)
_VALIDATION_FUNCTION_NAME = "get_validation_run_aggregates()"

# Split-based access restriction messages
_VALID_TEST_FULL_SNAPSHOT_ONLY = (
    "'valid' split only allows full-snapshot evaluations (files_hash must be None). "
    "Run critic on whole-snapshot examples to measure terminal metric."
)

# Metrics query advice (used in run_grader message)
_FUNCTION_BASED_METRICS_ADVICE = (
    f"To get recall metrics, call the {_VALIDATION_FUNCTION_NAME} SQL function. "
    "This function returns per-run aggregate metrics (total_credit, n_occurrences per run). "
    "You must aggregate across runs manually if needed."
)

_VIEW_BASED_METRICS_ADVICE = (
    "To get recall metrics, query the aggregated_recall_by_prompt or aggregated_recall_by_example views. "
    "These views pre-aggregate occurrence-level credits across multiple runs and include stats (n_examples, n_runs, ucb, lcb)."
)


# =============================================================================
# State and Input Models
# =============================================================================


@dataclass
class PromptOptimizerState:
    """Container for prompt optimizer run state.

    Tracks whether the optimizer completed successfully or reported an error.
    Used by AbortIf handler to stop the agent loop when the optimizer declares
    the run unsuccessful.
    """

    error: str | None = None


class ReportFailureInput(OpenAIStrictModeBaseModel):
    """Input for report_failure tool."""

    message: str = Field(description="Error message explaining why optimization could not be completed")


def _trace_query_advice(
    *,
    snapshot_slug: str | None = None,
    critique_id: str | None = None,
    run_id: str | None = None,
    transcript_id: str | None = None,
) -> str:
    """Generate advice for querying execution traces.

    Args:
        snapshot_slug: For critic runs (when run_id not available yet)
        critique_id: For grader runs (when run_id not available yet)
        run_id: Critic run ID or grader run ID (preferred when available)
        transcript_id: Transcript ID (optional, adds to query examples)

    At least one identifying parameter must be provided.
    """
    if run_id or transcript_id:
        # We have specific IDs - provide concrete query examples
        if critique_id:
            # Grader context
            base_msg = f"Grader run ID: {run_id or '(query grader_runs by critique_id)'}"
            if transcript_id:
                base_msg += f"\nTranscript ID: {transcript_id}"

            examples = [
                "\nQuery examples:",
                "-- Get grader run details:",
                f"SELECT * FROM grader_runs WHERE id = '{run_id}';"
                if run_id
                else f"SELECT * FROM grader_runs WHERE critique_id = '{critique_id}';",
            ]
            if transcript_id:
                examples.extend(
                    [
                        "\n-- Get execution trace (tool calls, reasoning, etc.):",
                        f"SELECT event_type, payload FROM events WHERE transcript_id = '{transcript_id}' ORDER BY sequence_num;",
                        "\n-- Get reasoning summaries only:",
                        f"SELECT payload FROM events WHERE transcript_id = '{transcript_id}' AND event_type = 'reasoning' ORDER BY sequence_num;",
                    ]
                )
            return base_msg + "\n" + "\n".join(examples)
        # Critic context
        base_msg = f"Critic run ID: {run_id or '(query critic_runs by snapshot_slug)'}"
        if transcript_id:
            base_msg += f"\nTranscript ID: {transcript_id}"

        examples = [
            "\nQuery examples:",
            "-- Get critic run details:",
            f"SELECT * FROM critic_runs WHERE id = '{run_id}';"
            if run_id
            else f"SELECT * FROM critic_runs WHERE snapshot_slug = '{snapshot_slug}';",
        ]
        if transcript_id:
            examples.extend(
                [
                    "\n-- Get execution trace (tool calls, reasoning, etc.):",
                    f"SELECT event_type, payload FROM events WHERE transcript_id = '{transcript_id}' ORDER BY sequence_num;",
                    "\n-- Get reasoning summaries only:",
                    f"SELECT payload FROM events WHERE transcript_id = '{transcript_id}' AND event_type = 'reasoning' ORDER BY sequence_num;",
                ]
            )
        return base_msg + "\n" + "\n".join(examples)

    # Fallback: only have snapshot_slug or critique_id (should rarely happen)
    if snapshot_slug is not None:
        return f"Query critic_runs table WHERE snapshot_slug='{snapshot_slug}' to get run IDs and transcript IDs."
    if critique_id is not None:
        return f"Query grader_runs table WHERE critique_id='{critique_id}' to get run IDs and transcript IDs."

    raise ValueError("At least one identifying parameter must be provided")


# ============================================================================
# Bootstrap Helper
# ============================================================================


def _read_package_files(
    builder: TypedBootstrapBuilder, runtime: Mounted[ContainerExecServer], package: str, files: list[str]
) -> list[FunctionCallItem]:
    """Helper to generate multiple read_package_file_call invocations."""
    return [read_package_file_call(builder, runtime, package, f) for f in files]


def make_po_bootstrap_calls(
    builder: TypedBootstrapBuilder,
    resources: Mounted[ResourcesServer],
    runtime: Mounted[ContainerExecServer],
    prompt_eval: "Mounted[PromptEvalServer]",
    target_metric: TargetMetric,
) -> list[FunctionCallItem]:
    """Build bootstrap calls: reads PO run ID, critic template, example query scripts, and research docs.

    Args:
        builder: Bootstrap builder for generating typed tool calls
        resources: Mounted resources server (comp.resources)
        runtime: Mounted runtime server (comp.runtime)
        prompt_eval: Mounted prompt eval server
        target_metric: Optimization mode (determines which example query files to load)
    """
    return [
        # System overview (snapshots, database, critic architecture, evaluation flow)
        *_read_package_files(builder, runtime, "adgn.props.docs", ["system_overview.md"]),
        # Database view definitions (show schema for aggregated recall views)
        docker_exec_call_mounted(
            builder,
            runtime,
            cmd=[
                "psql",
                "-c",
                "\\d+ aggregated_recall_by_prompt",
                "-c",
                "\\d+ aggregated_recall_by_example",
                "-c",
                "\\d+ occurrence_statistics",
                "-c",
                "\\d+ occurrence_credits",
            ],
            timeout_ms=5000,
        ),
        # Prompt optimization run ID
        builder.read_resource(
            resources, server=prompt_eval.prefix, uri=prompt_eval.server.optimization_run_id_resource.uri, max_bytes=256
        ),
        # Critic template structure
        *_read_package_files(builder, runtime, "adgn.props.critic", ["prompts/critic_system.j2.md"]),
        # Database query examples (base queries always included)
        *_read_package_files(
            builder,
            runtime,
            "adgn.props.examples",
            [
                "working_with_examples.py",  # Example schema (composite key pattern)
                "analyzing_critic_failures.py",  # Critic runs, grader results, execution traces
                "query_top_prompts.py",
                "query_train_examples.py",
                "query_run_status.py",
                "query_execution_traces.py",
            ]
            + (
                # Target-metric-specific query files
                ["query_train_vs_valid_performance_whole_repo.py", "query_full_snapshot_train_examples.py"]
                if target_metric == TargetMetric.WHOLE_REPO
                else ["query_train_vs_valid_performance_targeted.py"]
            ),
        ),
        # Prompt engineering research (best practices and patterns)
        *_read_package_files(
            builder,
            runtime,
            "adgn.props.prompt_optimize.research",
            ["meta_prompting.md", "anthropic_best_practices.md", "automatic_optimization.md"],
        ),
    ]


# ============================================================================
# MCP Compositor for Prompt Optimization
# ============================================================================


class PromptOptimizerCompositor(PropertiesDockerCompositor):
    """Compositor with prompt optimizer servers and temporary database user management.

    Inherits from PropertiesDockerCompositor, which provides:
    - runtime: Docker exec server (mounted by parent class)

    Adds:
    - prompt_eval: Prompt evaluation server (critic/grader orchestration)
    - Temporary database user with TRAIN-split-only access (via PromptOptimizerUserManager)

    Fixed configuration (NOT overridable):
    - workspace_mode: "rw" (agent needs write access for prompt files)
    - ephemeral: False (persistent container for optimization session)
    - mount_properties: False (properties not needed in container)

    Usage:
        async with PromptOptimizerCompositor(
            workspace_root=Path("/workspace"),
            docker_client=docker_client,
            critic_client=build_client(critic_model),
            grader_client=build_client(grader_model),
            hydrator=test_specimens_hydrator,
            prompt_optimization_run_id=uuid4(),
            db_config=config,  # Full database config (handles both user creation and container access)
            budget_limit=1.0,
        ) as comp:
            # Access servers via Mounted[T] wrappers:
            upsert_tool_name = comp.prompt_eval.server.upsert_prompt_tool.name
            critic_tool_name = comp.prompt_eval.server.run_critic_on_example_tool.name
            grader_tool_name = comp.prompt_eval.server.run_grader_tool.name
    """

    # Mount prefix constant (SSOT for test infrastructure)
    PROMPT_EVAL_PREFIX = MCPMountPrefix("prompt_eval")

    # Mounted server attributes (runtime inherited, prompt_eval added here)
    prompt_eval: "Mounted[PromptEvalServer]"

    # State for tracking optimizer success/failure
    optimizer_state: PromptOptimizerState

    def __init__(
        self,
        workspace_root: Path,
        docker_client: aiodocker.Docker,
        *,
        critic_client: OpenAIModelProto,
        grader_client: OpenAIModelProto,
        hydrator: SnapshotHydrator,
        target_metric: TargetMetric,
        prompt_optimization_run_id: UUID,
        db_config: DatabaseConfig,
        budget_limit: float,
        verbose: bool = False,
        snapshot_slugs: Sequence[SnapshotSlug] = (),
        network_mode: str = PROPS_NETWORK_NAME,
    ):
        """Create compositor with prompt optimization dependencies and temporary user.

        Args:
            workspace_root: Path to workspace directory to mount in container.
            docker_client: Async Docker client (managed by caller).
            critic_client: OpenAI client for running critic evaluations
            grader_client: OpenAI client for running grader evaluations
            hydrator: Snapshot hydrator for source code extraction
            target_metric: Optimization mode (whole-repo vs targeted validation)
            prompt_optimization_run_id: ID of the optimization run (used for temp user creation)
            db_config: Full database config (for creating temporary user and container access)
            budget_limit: Dollar budget limit for optimization
            verbose: Verbose output flag
            snapshot_slugs: Snapshot slugs to hydrate and mount (parent handles automatically)
            network_mode: Docker network mode (default: PROPS_NETWORK_NAME for database access)

        Note:
            workspace_mode, ephemeral, and mount_properties are fixed and NOT overridable.
            db_conn is managed internally via temporary user creation.
            Snapshots are automatically hydrated and mounted by parent class.
        """
        # Store parameters for temp user creation and server mounting
        self._db_config = db_config
        self._prompt_optimization_run_id = prompt_optimization_run_id
        self._user_manager: PromptOptimizerUserManager | None = None
        self._temp_user_creds: TempUserCredentials | None = None

        # Create state for tracking optimizer success/failure
        self.optimizer_state = PromptOptimizerState()

        # Always pass fixed parameters to parent (db_conn will be set in __aenter__)
        super().__init__(
            workspace_root,
            docker_client,
            workspace_mode="rw",
            ephemeral=False,
            mount_properties=False,
            db_conn=None,  # Will be set to temp user credentials in __aenter__
            hydrator=hydrator,  # Parent will handle snapshot hydration and mounting
            snapshot_slugs=snapshot_slugs,
            network_mode=network_mode,
        )

        # Store PromptEvalServer parameters
        self._critic_client = critic_client
        self._grader_client = grader_client
        self._docker_client = docker_client
        self._hydrator = hydrator
        self._target_metric = target_metric
        self._workspace_root = workspace_root
        self._budget_limit = budget_limit
        self._verbose = verbose

    async def __aenter__(self):
        """Start compositor, create temporary user, and mount servers."""
        # Create temporary database user with TRAIN-split-only access
        self._user_manager = PromptOptimizerUserManager(self._db_config.admin, self._prompt_optimization_run_id)
        self._temp_user_creds = await self._user_manager.__aenter__()

        logger.info(
            f"Created temporary prompt optimizer user: {self._temp_user_creds.username} "
            f"(run_id={self._prompt_optimization_run_id})"
        )

        # Start parent compositor (mounts resources, compositor_meta, runtime with temp user credentials)
        await super().__aenter__()

        # Mount prompt eval server with individual parameters
        self.prompt_eval = await self.mount_inproc(
            "prompt_eval",
            PromptEvalServer(
                critic_client=self._critic_client,
                grader_client=self._grader_client,
                docker_client=self._docker_client,
                hydrator=self._hydrator,
                db_config=self._db_config,
                optimizer_state=self.optimizer_state,
                target_metric=self._target_metric,
                prompt_optimization_run_id=self._prompt_optimization_run_id,
                workspace_root=self._workspace_root,
                budget_limit=self._budget_limit,
                verbose=self._verbose,
            ),
            pinned=True,
        )

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up servers and temporary user."""
        # First, clean up parent compositor (unmount servers, stop containers)
        try:
            await super().__aexit__(exc_type, exc_val, exc_tb)
        finally:
            # Always clean up temporary user, even if parent cleanup fails
            if self._user_manager is not None:
                await self._user_manager.__aexit__(exc_type, exc_val, exc_tb)
                logger.info(f"Cleaned up temporary prompt optimizer user (run_id={self._prompt_optimization_run_id})")

    def _create_docker_server(self, image_id: str) -> ContainerExecServer:
        """Create ContainerExecServer with temporary user credentials.

        Overrides parent to use _temp_user_creds instead of _db_conn.
        """
        # Build Docker volume binds
        binds: list[BindMount] = [
            BindMount(host_path=self._workspace_root.resolve(), container_path=WORKING_DIR, mode=self._workspace_mode)
        ]
        if self._extra_binds:
            binds.extend(self._extra_binds)

        # Build container environment variables
        env = {
            "XDG_CACHE_HOME": "/tmp",
            "RUFF_CACHE_DIR": "/tmp/.ruff_cache",
            "MYPY_CACHE_DIR": "/tmp/.mypy_cache",
            "TMPDIR": "/tmp",
            "TMP": "/tmp",
            "TEMP": "/tmp",
            "PYTHONPYCACHEPREFIX": "/tmp/__pycache__",
        }

        # Use temporary user credentials for database access (container-to-container)
        if self._temp_user_creds:
            container_config = self._db_config.for_container_user(self._temp_user_creds)
            env.update(container_config.to_env_dict())
        else:
            logger.warning("No temp user credentials available - container will not have database access")

        if self._extra_env:
            env.update(self._extra_env)
            logger.info(f"Injecting extra environment variables: {list(self._extra_env.keys())}")

        return ContainerExecServer(
            self._docker_client,
            ContainerOptions(
                image=image_id,
                working_dir=WORKING_DIR,
                binds=binds,
                environment=env,
                ephemeral=self._ephemeral,
                network_mode=self._network_mode,
            ),
        )


# ============================================================================
# MCP Server for Prompt Evaluation
# ============================================================================


# --- MCP Tool Input Types ---


class UpsertPromptInput(OpenAIStrictModeBaseModel):
    """Input for upsert_prompt tool."""

    file_path: str = Field(description="Path to prompt file in container filesystem (e.g., /workspace/prompt-v1.txt)")


class UpsertPromptOutput(OpenAIStrictModeBaseModel):
    """Output for upsert_prompt tool."""

    prompt_sha256: str = Field(description="SHA256 hash of prompt content (use this in run_critic)")


class RunCriticOnExampleInput(OpenAIStrictModeBaseModel):
    """Run critic on a snapshot with specified file scope.

    Returns critic_run_id and critique_id for subsequent grading.

    Mode-specific restrictions (enforced by RLS + MCP):
    - Whole-Repo Mode: VALID split requires entire_snapshot scope
    - Targeted Mode: VALID split allows both entire_snapshot and specific_files scopes
    - TRAIN split: Both scopes allowed in all modes
    """

    snapshot_slug: SnapshotSlug = Field(description="Snapshot slug (e.g., ducktape/2025-11-26-00)")
    scope: CriticScopeSpec = Field(
        description="File scope specification: entire_snapshot or specific_files with file list"
    )
    prompt_sha256: str = Field(description="SHA256 hash of the system prompt (from upsert_prompt)")
    max_turns: int = Field(ge=200, le=200, description="Maximum sampling turns (fixed at 200)")


class RunCriticOutput(OpenAIStrictModeBaseModel):
    """Output for run_critic tool - DB IDs for critic run and generated critique."""

    critic_run_id: UUID = Field(description="critic_runs.id - Query critic_runs table for output, costs, model.")
    critique_id: UUID = Field(description="critiques.id - Pass to run_grader to grade against ground truth.")
    # cumulative_cost_usd: float = Field(
    #     description="Total cumulative cost (USD) for all critic/grader runs in this optimization session so far."
    # )


class RunGraderInput(OpenAIStrictModeBaseModel):
    """Input for run_grader tool.

    Note: model is NOT included - the server is bound to a specific client/model at build time.
    """

    critique_id: UUID = Field(description="critiques.id - The critique to grade (from run_critic output)")
    max_turns: int = Field(ge=200, le=200, description="Maximum sampling turns (fixed at 200)")


class RunGraderOutput(OpenAIStrictModeBaseModel):
    """Output for run_grader tool - DB ID and instructions for querying metrics."""

    grader_run_id: UUID = Field(description="grader_runs.id - Grader run has been saved to database.")
    message: str = Field(
        description="Instructions for querying recall metrics from database views (aggregated across runs)."
    )
    # cumulative_cost_usd: float = Field(
    #     description="Total cumulative cost (USD) for all critic/grader runs in this optimization session so far."
    # )


class PromptEvalServer(EnhancedFastMCP):
    """Prompt eval MCP server with typed resource/tool access.

    Tool name constants (SSOT for tests):
    - UPSERT_PROMPT_TOOL = "upsert_prompt"
    - RUN_CRITIC_ON_EXAMPLE_TOOL = "run_critic_on_example"
    - RUN_GRADER_TOOL = "run_grader"

    Provides MCP tools for triggering critic and grader runs:
    - upsert_prompt(file_path) -> prompt_sha256
    - run_critic_on_example(snapshot_slug, scope, prompt_sha256) -> critic_run_id, critique_id
    - run_grader(critique_id) -> grader_run_id

    Tools return only DB IDs. Agent queries database for results, metrics, costs.

    TODO: Implement proper cost tracking and limiting
    Implementation approach:
    - Enforcement: Check if total_cost > budget_limit before accepting run_critic/run_grader calls
    - Tracking: After each run completes, fetch run_id from DB, pull its costs field, add to running tally
    - Storage option 1: In-memory running tally in server state (simple, per-session)
    - Storage option 2: Create PromptOptimizationRun DB model with parent pointer to group related runs
      - Aggregate costs across all child critic_runs/grader_runs linked to the optimization session
      - Persist budget and accumulated costs for resumability

    TODO: Add max wall time constraint for critic runs (5 minutes)
    Context: Critic agents can get stuck in loops (e.g., running 232 consecutive ls commands)
    See: src/adgn/props/docs/looping-analysis-2025-12-08/ for detailed analysis
    Implementation approach:
    - Add timeout parameter to execute_critic_run in critic.critic module
    - Wrap critic agent.run() with asyncio.timeout() or similar
    - On timeout, save partial results to DB with timeout flag
    - Return timeout status in RunCriticOutput so optimizer can adapt
    - Consider: Should timeout count as "failed" run or "partial success" for metrics?

    TODO: Consider system message anti-repetition hook (NOT static prompt fix)
    Context: Agents can get stuck repeating the same tool calls (ls, read, etc.)
    See: src/adgn/props/docs/looping-analysis-2025-12-08/smoking-gun-findings.md
    Root cause: Agent didn't know directory contents are stable, kept re-checking
    Goal: Dynamic hook that detects and intervenes on repetitive behavior patterns
    Implementation approaches:
    - Option 1: Event handler that injects system message warnings
      - Monitor tool call history (e.g., last 10-20 calls)
      - Detect patterns: same tool+args called 3+ times
      - Inject warning into system message dynamically:
        "WARNING: You've called docker_exec(ls /path) 3 times. Directory contents are STABLE and cannot change."
      - Could append to system message or inject as a synthetic user message
      - Implementation: Event handler watching ToolCall events, modifying agent state
    - Option 2: MCP server-side warning in tool response metadata
      - Docker exec server tracks recent calls per session
      - When detecting repetition (same cmd 3+ times), add warning field to response
      - Agent sees: {"exit": ..., "stdout": ..., "warning": "Repeated call detected"}
      - Simpler than Option 1, doesn't require system message manipulation
    - Option 3: Tool policy that blocks excessive repetition
      - Similar to budget enforcement, but tracks call signatures
      - After N identical calls, policy prevents further identical calls
      - Returns error: "Tool call blocked: identical to last 5 calls"
      - Most aggressive, could break legitimate use cases
    Recommendation: Start with Option 2 (MCP server-side warnings)
    - Least invasive, doesn't modify agent internals
    - Can evolve to Option 1 if warnings aren't effective
    - Option 3 as last resort if warnings fail
    """

    # Tool name constants (SSOT for tests)
    UPSERT_PROMPT_TOOL = "upsert_prompt"
    RUN_CRITIC_ON_EXAMPLE_TOOL = "run_critic_on_example"
    RUN_GRADER_TOOL = "run_grader"

    # Resource attributes (stashed results of @resource decorator - single source of truth for URI access)
    optimization_run_id_resource: FunctionResource

    # Tool references (assigned in __init__)
    upsert_prompt_tool: FunctionTool
    run_critic_on_example_tool: FunctionTool
    run_grader_tool: FunctionTool
    report_failure_tool: FunctionTool

    def __init__(
        self,
        *,
        critic_client: OpenAIModelProto,
        grader_client: OpenAIModelProto,
        docker_client: aiodocker.Docker,
        hydrator: SnapshotHydrator,
        db_config: DatabaseConfig,
        optimizer_state: PromptOptimizerState,
        target_metric: TargetMetric,
        prompt_optimization_run_id: UUID,
        workspace_root: Path,
        budget_limit: float,
        verbose: bool = False,
    ):
        """Create prompt eval server bound to clients and configuration.

        Args:
            critic_client: OpenAI client for running critic evaluations
            grader_client: OpenAI client for running grader evaluations
            docker_client: Async Docker client for container operations
            hydrator: Snapshot hydrator for source code extraction
            db_config: Database configuration (from CLI caller)
            optimizer_state: Shared state for tracking optimizer success/failure
            target_metric: Optimization mode (whole-repo vs targeted validation)
            prompt_optimization_run_id: ID of the optimization run for tracking prompts
            workspace_root: Working directory for reading prompt files
            budget_limit: Dollar budget limit for optimization (currently not enforced)
            verbose: Verbose output flag
        """
        super().__init__(
            "prompt_eval",
            instructions=(
                "Prompt optimization tools: save prompts to database (upsert_prompt), "
                "run critic agents on training examples (run_critic_on_example), "
                "grade critiques against ground truth (run_grader). "
                "Query the database for results, costs, and metrics. "
                "Use report_failure to declare the run unsuccessful and abort."
            ),
        )

        # Store parameters for use in tools
        self._critic_client = critic_client
        self._grader_client = grader_client
        self._docker_client = docker_client
        self._hydrator = hydrator
        self._db_config = db_config
        self._optimizer_state = optimizer_state
        self._target_metric = target_metric
        self._prompt_optimization_run_id = prompt_optimization_run_id
        self._workspace_root = workspace_root
        self._budget_limit = budget_limit
        self._verbose = verbose

        # Register resource and stash the result
        async def get_prompt_optimization_run_id() -> UUID:
            """Get the prompt optimization run ID for this session.

            Returns UUID object (serialized to string in JSON).
            Use this to query costs via query_builders.po_run_costs(po_run_id).
            """
            return prompt_optimization_run_id

        self.optimization_run_id_resource = cast(
            FunctionResource,
            self.resource("resource://prompt_eval/prompt_optimization_run_id")(get_prompt_optimization_run_id),
        )

        # Register tools - names derived from function names
        async def upsert_prompt(payload: UpsertPromptInput) -> UpsertPromptOutput:
            """Save prompt to database and return SHA256 hash.

            Write prompt file using heredoc: bash -c "cat > /workspace/prompt-v1.md << 'EOF' ... EOF"
            Then call this tool with the file path. Returns hash for use in run_critic_on_example.
            """
            # Map container path to host path
            # Container paths like /workspace/prompt-v1.txt map to workspace_root/prompt-v1.txt
            container_path = Path(payload.file_path)
            working_dir_str = str(WORKING_DIR) + "/"
            if not str(container_path).startswith(working_dir_str):
                raise ToolError(f"File path must be in {WORKING_DIR}/ directory, got: {payload.file_path}")

            relative_path = str(container_path).removeprefix(working_dir_str)
            host_path = workspace_root / relative_path

            if not host_path.exists():
                raise ToolError(
                    f"Prompt file not found at {payload.file_path}. "
                    f"First write the file using docker_exec with bash heredoc:\n"
                    f"bash -c \"cat > {payload.file_path} << 'EOF'\n"
                    f"<your prompt text>\n"
                    f'EOF"\n'
                    f"Then call upsert_prompt with file_path={payload.file_path}"
                )

            # Read prompt text from host filesystem
            prompt_text = host_path.read_text(encoding="utf-8")

            # Hash and upsert to database (with optional run ID for tracking)
            prompt_sha256 = hash_and_upsert_prompt(prompt_text, prompt_optimization_run_id)

            return UpsertPromptOutput(prompt_sha256=prompt_sha256)

        self.upsert_prompt_tool = self.flat_model()(upsert_prompt)

        async def run_critic_on_example(payload: RunCriticOnExampleInput) -> RunCriticOutput:
            """Run critic on a snapshot with specified file scope.

            Validates split-based access restrictions:
            - TRAIN split: all scopes allowed
            - VALID split: only entire_snapshot scope allowed (no per-file examples)
            - TEST split: completely off-limits

            The scope can be constructed from pre-defined examples or used directly.
            """
            # Load and validate snapshot
            with get_session() as session:
                db_snapshot = session.query(Snapshot).filter_by(slug=payload.snapshot_slug).one_or_none()
                if not db_snapshot:
                    raise ToolError(f"Snapshot {payload.snapshot_slug} not found")

                # Validate split-based access restrictions
                if db_snapshot.split == Split.TEST:
                    # TEST split: no access at all
                    raise ToolError(
                        f"Access denied: 'test' split is completely off-limits. "
                        f"You can only run evaluations on 'train' and 'valid' splits. "
                        f"Snapshot {payload.snapshot_slug} is in 'test' split."
                    )

                # Check if scope is specific_files (per-file example)
                is_specific_files = isinstance(payload.scope, ExplicitFileScope)

                # Check VALID scope restrictions based on target metric mode
                if (
                    db_snapshot.split == Split.VALID
                    and is_specific_files
                    and self._target_metric == TargetMetric.WHOLE_REPO
                ):
                    # Whole-repo mode: only allow full-snapshot evaluations
                    raise ToolError(
                        "valid split in whole-repo mode requires entire_snapshot scope. "
                        "You requested specific_files. Use entire_snapshot instead."
                    )
                # Targeted mode: allow specific_files (no error)

                # Validate that specific_files scope corresponds to a valid example
                if is_specific_files:
                    assert isinstance(payload.scope, ExplicitFileScope)
                    requested_files = sorted(payload.scope.files)
                    files_hash = hash_file_set(requested_files)

                    # Check if example exists
                    example = (
                        session.query(Example)
                        .filter_by(snapshot_slug=payload.snapshot_slug, files_hash=files_hash)
                        .one_or_none()
                    )

                    if not example:
                        # List available examples for this snapshot
                        available = session.query(Example).filter_by(snapshot_slug=payload.snapshot_slug).all()
                        example_list = "\n".join(f"  - {ex.files}" for ex in available[:10])
                        if len(available) > 10:
                            example_list += f"\n  ... and {len(available) - 10} more"

                        raise ToolError(
                            f"No example found for files {requested_files} in snapshot {payload.snapshot_slug}.\n"
                            f"Available examples ({len(available)} total):\n{example_list}\n\n"
                            f"Query the examples table to find valid file combinations:\n"
                            f"SELECT files FROM examples WHERE snapshot_slug='{payload.snapshot_slug}';"
                        )

                # Use provided scope directly
                critic_input = CriticInput(
                    snapshot_slug=payload.snapshot_slug, files=payload.scope, prompt_sha256=payload.prompt_sha256
                )

            # Execute critic run (compositor handles snapshot hydration internally)
            try:
                (critic_output, critic_run_id, critique_id) = await execute_critic_run(
                    input_data=critic_input,
                    client=self._critic_client,
                    docker_client=self._docker_client,
                    hydrator=self._hydrator,
                    prompt_optimization_run_id=self._prompt_optimization_run_id,
                    mount_properties=False,
                    extra_handlers=(),
                    verbose=self._verbose,
                    max_turns=payload.max_turns,
                )
            except CriticExecutionError as e:
                raise ToolError(
                    f"Critic agent failed during execution: {e}\n\n"
                    f"{_trace_query_advice(snapshot_slug=payload.snapshot_slug)}"
                ) from e
            except CriticDidNotSubmitError as e:
                raise ToolError(
                    f"Critic agent did not call submit(): {e}\n\n"
                    f"{_AGENT_STUCK_ADVICE}\n"
                    f"{_trace_query_advice(snapshot_slug=payload.snapshot_slug)}"
                ) from e

            # Get transcript_id for detailed error messages
            with get_session() as session:
                critic_run = session.get(CriticRun, critic_run_id)
                transcript_id = str(critic_run.transcript_id) if critic_run else None

            # Check output type to provide specific error messages
            if isinstance(critic_output, CriticMaxTurnsExceeded):
                raise ToolError(
                    f"Critic agent exceeded maximum turns ({payload.max_turns}).\n\n"
                    f"{_AGENT_STUCK_ADVICE}\n"
                    f"{_trace_query_advice(run_id=str(critic_run_id), transcript_id=transcript_id)}"
                )
            if isinstance(critic_output, CriticContextLengthExceeded):
                raise ToolError(
                    f"Critic agent exceeded context length: {critic_output.error_message}\n\n"
                    f"{_AGENT_STUCK_ADVICE}\n"
                    f"{_trace_query_advice(run_id=str(critic_run_id), transcript_id=transcript_id)}"
                )

            # At this point critic_output must be CriticSuccess
            if critique_id is None:
                # This should never happen with CriticSuccess, but check anyway
                raise ToolError(
                    f"Internal error: Critic reported success but no critique was created. "
                    f"Query critic_runs with id={critic_run_id}."
                )

            return RunCriticOutput(critic_run_id=critic_run_id, critique_id=critique_id)

        self.run_critic_on_example_tool = self.flat_model()(run_critic_on_example)

        async def run_grader(payload: RunGraderInput) -> RunGraderOutput:
            """Run grader agent to evaluate a critique against ground truth.

            Saves grader run to database with per-occurrence credits.

            To get recall metrics, query aggregate views (see system_overview.md for details):
            - aggregated_recall_by_prompt: Recall per (prompt, models, split)
            - aggregated_recall_by_example: Recall per (example, models, split)

            Returns grader_run_id and instructions for querying metrics.
            """
            # Execute GraderRun by critique_id (fetches critique from DB, saves grader run to DB)
            with get_session() as session:
                try:
                    grader_run_id = await grade_critique_by_id(
                        session=session,
                        critique_id=payload.critique_id,
                        client=self._grader_client,
                        docker_client=self._docker_client,
                        hydrator=self._hydrator,
                        db_config=self._db_config,
                        prompt_optimization_run_id=self._prompt_optimization_run_id,
                        verbose=self._verbose,
                        max_turns=payload.max_turns,
                    )
                except (GraderDidNotSubmitError, MaxTurnsExceededError) as e:
                    # Try to find grader_run_id for better error messages
                    # (grader run is created in DB even if execution fails)
                    grader_run = (
                        session.query(DBGraderRun)
                        .filter_by(critique_id=payload.critique_id)
                        .order_by(DBGraderRun.created_at.desc())
                        .first()
                    )
                    grader_run_id_str = str(grader_run.id) if grader_run else None
                    transcript_id_str = str(grader_run.transcript_id) if grader_run else None

                    if isinstance(e, GraderDidNotSubmitError):
                        raise ToolError(
                            f"Grader agent did not call submit(): {e}\n\n"
                            f"{_AGENT_STUCK_ADVICE}\n"
                            f"{_trace_query_advice(critique_id=str(payload.critique_id), run_id=grader_run_id_str, transcript_id=transcript_id_str)}"
                        ) from e
                    # MaxTurnsExceededError
                    raise ToolError(
                        f"Grader agent exceeded maximum turns ({payload.max_turns}): {e}\n\n"
                        f"{_AGENT_STUCK_ADVICE}\n"
                        f"{_trace_query_advice(critique_id=str(payload.critique_id), run_id=grader_run_id_str, transcript_id=transcript_id_str)}"
                    ) from e

                # Verify grader run succeeded
                grader_run = session.get(DBGraderRun, grader_run_id)
                if not grader_run:
                    raise ToolError(f"Grader run {grader_run_id} not found in database")
                if not grader_run.output:
                    raise ToolError(f"Grader run {grader_run_id} has no output")
                if not isinstance(grader_run.output, DBGraderSuccess):
                    raise ToolError(
                        f"Grader run {grader_run_id} exceeded max turns (no recall available)\n\n"
                        f"{_AGENT_STUCK_ADVICE}\n"
                        f"{_trace_query_advice(critique_id=str(payload.critique_id), run_id=str(grader_run_id), transcript_id=str(grader_run.transcript_id))}"
                    )

                # Determine split and whether this is a full-snapshot run
                split = grader_run.snapshot_obj.split
                critique = grader_run.critique_obj
                critic_run = critique.critic_run
                if not critic_run:
                    raise ToolError(f"Critique {critique.id} has no associated critic run")

                # Find matching example to check is_whole_snapshot
                example = (
                    session.query(Example)
                    .filter_by(snapshot_slug=critic_run.snapshot_slug, files_hash=critic_run.files_hash)
                    .one_or_none()
                )

                is_whole_snapshot = example.is_whole_snapshot if example else False

                # Compute immediate feedback from this grader run
                occurrence_results = grader_run.output.occurrence_results
                total_credit = sum(occ.found_credit for occ in occurrence_results)
                max_credit = len(occurrence_results)

                # Build message with immediate feedback and query advice
                immediate_feedback = (
                    f"Grader run {grader_run_id} completed successfully. "
                    f"Total credit: {total_credit:.2f} of {max_credit}. "
                )

                # Add query advice based on split, example type, and optimization mode
                if split == Split.VALID and is_whole_snapshot and self._target_metric == TargetMetric.WHOLE_REPO:
                    # VALID full-snapshot in whole-repo mode: use validation function
                    query_advice = (
                        f"{_FUNCTION_BASED_METRICS_ADVICE} "
                        f"Example: SELECT * FROM {_VALIDATION_FUNCTION_NAME} WHERE grader_run_id = '{grader_run_id}'; "
                        f"For full details, query: SELECT output FROM grader_runs WHERE id = '{grader_run_id}';"
                    )
                elif split == Split.VALID and is_whole_snapshot and self._target_metric == TargetMetric.TARGETED:
                    # VALID full-snapshot in targeted mode: use aggregate views
                    query_advice = (
                        f"{_VIEW_BASED_METRICS_ADVICE} "
                        "IMPORTANT: Check n_examples >= 5 before trusting metrics (small samples have high variance). "
                        "Use UCB/LCB bounds to quantify uncertainty. "
                        f"Example: SELECT recall, n_examples, ucb, lcb FROM aggregated_recall_by_prompt "
                        f"WHERE prompt_sha256='...' AND split='valid' AND is_whole_snapshot=true; "
                        f"For full details, query: SELECT output FROM grader_runs WHERE id = '{grader_run_id}';"
                    )
                else:
                    # TRAIN split or per-file examples: use aggregate views
                    query_advice = (
                        f"{_VIEW_BASED_METRICS_ADVICE} "
                        "Example: SELECT recall FROM aggregated_recall_by_prompt WHERE prompt_sha256='...' AND split='train'; "
                        f"For full details, query: SELECT output FROM grader_runs WHERE id = '{grader_run_id}';"
                    )

                message = immediate_feedback + query_advice

            return RunGraderOutput(grader_run_id=grader_run_id, message=message)

        self.run_grader_tool = self.flat_model()(run_grader)

        async def report_failure(payload: ReportFailureInput) -> str:
            """Report that optimization could not be completed.

            Use this when you determine the optimization run should be aborted
            (e.g., critical errors, no viable path forward).

            The agent loop will be stopped after this tool returns.
            """
            self._optimizer_state.error = payload.message
            return f"Optimization run marked as unsuccessful: {payload.message}"

        self.report_failure_tool = self.flat_model()(report_failure)


# ============================================================================
# Prompt Optimizer
# ============================================================================


async def run_prompt_optimizer(
    budget: float,
    ctx: RunsContext,
    hydrator: SnapshotHydrator,
    optimizer_client: OpenAIModelProto,
    critic_client: OpenAIModelProto,
    grader_client: OpenAIModelProto,
    docker_client: aiodocker.Docker,
    target_metric: TargetMetric,
    out_dir: Path | None = None,
    verbose: bool = False,
    max_lines: int = DEFAULT_MAX_LINES,
) -> None:
    """Run a Prompt Engineering agent to optimize a critic system prompt.

    Args:
        budget: Dollar budget for optimization
        ctx: Runs context for path derivation
        hydrator: Snapshot hydrator for source code extraction
        optimizer_client: OpenAI client for prompt optimizer agent
        critic_client: OpenAI client for running critic evaluations
        grader_client: OpenAI client for running grader evaluations
        docker_client: Async Docker client for container operations
        target_metric: Optimization mode (whole-repo vs targeted validation)
        out_dir: Optional output directory
        verbose: Verbose output flag
        max_lines: Maximum lines for formatting tool responses

    Hydrates train snapshots and mounts them with definitions via Docker.
    The agent can query train data and valid aggregates via database (temporary user with RLS).
    """
    # Render system prompt with target_metric for conditional guidance
    system = render_prompt_template(
        "prompt_optimize/prompts/prompt_optimizer_system.j2.md", target_metric=target_metric.value
    )

    # Session directory (inline adhoc_run_dir - only called here)
    ts = format_timestamp_session()
    if out_dir is not None:
        session_dir = out_dir.resolve()
    else:
        session_dir = ctx.base_dir / "prompt_optimize" / f"session_{ts}"
        session_dir.mkdir(parents=True, exist_ok=True)
        session_dir = session_dir.resolve()

    # Get train snapshots from database
    with get_session() as session:
        train_snapshots = session.query(Snapshot).filter_by(split=Split.TRAIN.value).all()
        train_slugs = [SnapshotSlug(s.slug) for s in train_snapshots]

    logger.info(f"Will mount {len(train_slugs)} train snapshots (compositor will handle hydration)")

    # Get database config (fails fast if env vars not set)
    config = get_database_config()

    # Generate transcript ID for database event tracking
    transcript_id = uuid4()
    logger.info(f"Prompt optimizer transcript_id: {transcript_id}")

    with get_session() as session:
        po_run = PromptOptimizationRun(
            transcript_id=transcript_id,
            budget_limit=budget,
            config={
                "optimizer_model": optimizer_client.model,
                "critic_model": critic_client.model,
                "grader_model": grader_client.model,
                "target_metric": target_metric.value,
                "session_dir": str(session_dir),
            },
        )
        session.add(po_run)
        session.flush()
        prompt_optimization_run_id = po_run.id
        session.commit()

    logger.info(f"Created PromptOptimizationRun: {prompt_optimization_run_id}")

    # Create compositor with Docker runtime, prompt eval server, and temporary user
    # workspace_root (session_dir) will be mounted as /workspace (rw mode for agent to write prompts)
    # Compositor internally creates a temporary database user with TRAIN-split-only access
    # Compositor also handles snapshot hydration and mounting automatically
    async with PromptOptimizerCompositor(
        workspace_root=session_dir,
        docker_client=docker_client,
        critic_client=critic_client,
        grader_client=grader_client,
        hydrator=hydrator,
        target_metric=target_metric,
        prompt_optimization_run_id=prompt_optimization_run_id,
        db_config=config,  # Full database config (handles both user creation and container access)
        budget_limit=budget,
        verbose=verbose,
        snapshot_slugs=train_slugs,  # Compositor will hydrate and mount these automatically
        network_mode=PROPS_NETWORK_NAME,  # Join postgres network for database access
    ) as comp:
        # Servers already mounted by PromptOptimizerCompositor:
        # - comp.runtime (Docker exec server)
        # - comp.prompt_eval (Prompt evaluation server)

        # TODO: Auto-infer prompt_optimization_run_id in MCP server tools instead of manually passing it here
        # The prompt eval server (and grader/critic tools) should be able to auto-detect when they're
        # being called within a PO session context (e.g., via environment variable, session metadata,
        # or resource lookup) rather than requiring manual ID propagation through all tool calls.
        # This would eliminate the need to manually set prompt_optimization_run_id in RunCriticInput
        # and RunGraderInput.

        user = f"""Your budget is: ${budget:.2f}.

Models in use:
- Optimizer (you): {optimizer_client.model}
- Critic: {critic_client.model}
- Grader: {grader_client.model}

Note: The database may contain results from other models. These historical results might provide useful insights for optimization.

Iterate to find an optimal prompt for a code reviewer/critic LLM agent.
Prioritize recall.
"""

        # Use the prompt_eval server reference for introspection
        builder = TypedBootstrapBuilder.for_server(comp.prompt_eval.server)
        bootstrap_calls = make_po_bootstrap_calls(
            builder,
            resources=comp.resources,
            runtime=comp.runtime,
            prompt_eval=comp.prompt_eval,
            target_metric=target_metric,
        )
        bootstrap = SequenceHandler([InjectItems(items=bootstrap_calls)])

        def _optimizer_should_abort() -> bool:
            """Check if optimizer reported failure."""
            return comp.optimizer_state.error is not None

        handlers: list = [
            bootstrap,
            *await build_props_handlers(
                transcript_id=transcript_id,
                verbose_prefix=(f"[OPTIMIZER:{short_uuid(transcript_id)}] " if verbose else None),
                compositor=comp,
                max_lines=max_lines,
            ),
            RedirectOnTextMessageHandler(
                reminder_message=(
                    "You are not in an interactive conversation. Your task is to optimize "
                    "the critic prompt by using the provided MCP tools (run_critic_on_example, "
                    "run_grader, upsert_prompt) to evaluate different prompts and improve "
                    "validation recall. Please use the tools to continue your optimization work."
                )
            ),
            AbortIf(should_abort=_optimizer_should_abort),
        ]
        # Note: resources and compositor_meta are auto-mounted by base Compositor
        async with Client(comp) as mcp_client:
            agent = await Agent.create(
                mcp_client=mcp_client,
                client=optimizer_client,
                handlers=handlers,
                parallel_tool_calls=True,
                reasoning_summary=ReasoningSummary.detailed,
                tool_policy=AllowAnyToolOrTextMessage(),
            )

            # Add budget enforcement handler after agent creation (needs agent reference)
            budget_handler = BudgetEnforcementHandler(
                prompt_optimization_run_id=prompt_optimization_run_id, budget_limit=budget, agent=agent
            )
            agent._handlers.append(budget_handler)

            agent.insert_messages([SystemMessage.text(system), UserMessage.text(user)])
            await agent.run()
    # Compositor.__aexit__ unmounts all non-pinned servers and cleans up containers here

    logger.info(f"Optimization session complete. Results in: {session_dir}")
    logger.info(f"Budget: ${budget:.2f}")

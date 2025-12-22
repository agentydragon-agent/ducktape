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
from uuid import UUID, uuid4

import aiodocker
from fastmcp.client import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AuthProvider
from fastmcp.tools import FunctionTool
from pydantic import Field
from sqlalchemy import func

from adgn.agent.display import CompactDisplayHandler
from adgn.agent.handler import AbortIf, RedirectOnTextMessageHandler
from adgn.agent.turn_limit import MaxTurnsExceededError
from adgn.mcp._shared.constants import WORKING_DIR
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.openai_utils.model import OpenAIModelProto, UserMessage
from adgn.openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel
from adgn.openai_utils.types import ReasoningSummary
from adgn.props.agent_handle import AgentHandle
from adgn.props.agent_setup import AgentEnvironment
from adgn.props.agent_types import AgentType, PromptOptimizerTypeConfig
from adgn.props.agent_workspace import WorkspaceManager
from adgn.props.cli.common_options import DEFAULT_MAX_LINES
from adgn.props.critic.critic import run_critic as execute_critic_run
from adgn.props.critic.exceptions import CriticDidNotSubmitError, CriticExecutionError
from adgn.props.db import get_session
from adgn.props.db.agent_definition_ids import PROMPT_OPTIMIZER_AGENT_DEFINITION_ID
from adgn.props.db.config import DatabaseConfig
from adgn.props.db.examples import Example
from adgn.props.db.models import AgentDefinition, AgentRun, AgentRunStatus, GradingDecision, Snapshot
from adgn.props.definition_utils import pack_definition, validate_definition
from adgn.props.display import short_uuid
from adgn.props.grader.exceptions import GraderDidNotSubmitError
from adgn.props.grader.grader import grade_critic_run_by_id
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import AllFilesScope, ExplicitFileScope, ScopeKind
from adgn.props.prompt_optimize.budget_handler import BudgetEnforcementHandler
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
    "'valid' split only allows full-snapshot evaluations (scope_hash must be None). "
    "Run critic on whole-snapshot examples to measure terminal metric."
)

# Metrics query advice (used in run_grader message)
_FUNCTION_BASED_METRICS_ADVICE = (
    f"To get recall metrics, call the {_VALIDATION_FUNCTION_NAME} SQL function. "
    "This function returns per-run aggregate metrics (total_credit, n_occurrences per run). "
    "You must aggregate across runs manually if needed."
)

_VIEW_BASED_METRICS_ADVICE = (
    "To get recall metrics, query the aggregated_recall_by_definition or aggregated_recall_by_example views. "
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
    critic_run_id: UUID | None = None,
    run_id: UUID | None = None,
    is_grader: bool = False,
) -> str:
    """Generate advice for querying execution traces.

    Args:
        snapshot_slug: For critic runs (when run_id not available yet)
        critic_run_id: For grader runs (link to critic_run_id)
        run_id: Agent run ID (agent_run_id from AgentRun table)
        is_grader: True if this is grader context, False for critic context

    At least one identifying parameter must be provided.
    """
    # Convert UUIDs to strings for SQL query examples
    run_id_str = str(run_id) if run_id else None
    critic_run_id_str = str(critic_run_id) if critic_run_id else None
    if run_id_str:
        # We have specific run_id - provide concrete query examples
        if is_grader:
            # Grader context
            base_msg = f"Grader agent run ID: {run_id_str}"

            examples = [
                "\nQuery examples:",
                "-- Get grader run details:",
                f"SELECT * FROM agent_runs WHERE agent_run_id = '{run_id_str}';",
                "\n-- Get execution trace (tool calls, reasoning, etc.):",
                f"SELECT event_type, payload FROM events WHERE agent_run_id = '{run_id_str}' ORDER BY sequence_num;",
                "\n-- Get reasoning summaries only:",
                f"SELECT payload FROM events WHERE agent_run_id = '{run_id_str}' AND event_type = 'reasoning' ORDER BY sequence_num;",
            ]
            return base_msg + "\n" + "\n".join(examples)
        # Critic context
        base_msg = f"Critic agent run ID: {run_id_str}"

        examples = [
            "\nQuery examples:",
            "-- Get critic run details:",
            f"SELECT * FROM agent_runs WHERE agent_run_id = '{run_id_str}';",
            "\n-- Get execution trace (tool calls, reasoning, etc.):",
            f"SELECT event_type, payload FROM events WHERE agent_run_id = '{run_id_str}' ORDER BY sequence_num;",
            "\n-- Get reasoning summaries only:",
            f"SELECT payload FROM events WHERE agent_run_id = '{run_id_str}' AND event_type = 'reasoning' ORDER BY sequence_num;",
        ]
        return base_msg + "\n" + "\n".join(examples)

    # Fallback: only have snapshot_slug or critic_run_id (should rarely happen)
    if snapshot_slug is not None:
        return f"Query agent_runs WHERE type_config->>'snapshot_slug'='{snapshot_slug}' AND type_config->>'agent_type'='critic' to get run IDs."
    if critic_run_id_str is not None:
        return f"Query agent_runs WHERE type_config->>'graded_agent_run_id'='{critic_run_id_str}' AND type_config->>'agent_type'='grader' to get run IDs."

    raise ValueError("At least one identifying parameter must be provided")


# ============================================================================
# Prompt Optimizer Agent Environment
# ============================================================================


class PromptOptimizerAgentEnvironment(AgentEnvironment):
    """Agent environment for prompt optimizer with prompt_eval MCP server.

    Provides complete environment for prompt optimizer agents:
    - Temporary database user with TRAIN-split-only access (prompt_optimizer_agent_{run_id})
    - HTTP MCP server with prompt evaluation tools (upsert_prompt, run_critic_on_example, run_grader)
    - Docker container with docker_exec
    - Train snapshots mounted at /snapshots/<slug>/
    - Workspace mounted read-write at /workspace/ for prompt files

    Agent workflow:
    1. Writes prompt files to /workspace/
    2. Calls upsert_prompt to save to database
    3. Runs critic/grader via run_critic_on_example/run_grader tools
    4. Queries database for metrics and results
    5. Iterates on prompt improvements

    Usage:
        async with PromptOptimizerAgentEnvironment(
            workspace_root=Path("/workspace"),
            docker_client=docker_client,
            hydrator=hydrator,
            optimizer_run_id=uuid4(),
            critic_client=critic_client,
            grader_client=grader_client,
            db_config=config,
            optimizer_state=state,
            target_metric=TargetMetric.WHOLE_REPO,
            budget_limit=1.0,
            snapshot_slugs=[...],
        ) as compositor:
            # Run prompt optimizer agent
            ...
    """

    # Exposed for accessing server tools/resources programmatically
    prompt_eval_server: EnhancedFastMCP
    optimizer_state: PromptOptimizerState

    def __init__(
        self,
        docker_client: aiodocker.Docker,
        hydrator: SnapshotHydrator,
        optimizer_run_id: UUID,
        critic_client: OpenAIModelProto,
        grader_client: OpenAIModelProto,
        db_config: DatabaseConfig,
        optimizer_state: PromptOptimizerState,
        target_metric: TargetMetric,
        budget_limit: float,
        workspace_manager: WorkspaceManager,
        snapshot_slugs: Sequence[SnapshotSlug] = (),
        verbose: bool = False,
    ):
        """Create prompt optimizer agent environment.

        Args:
            docker_client: Async Docker client
            hydrator: Snapshot hydrator
            optimizer_run_id: UUID of the optimizer agent run (for RLS scoping)
            critic_client: OpenAI client for running critic evaluations
            grader_client: OpenAI client for running grader evaluations
            db_config: Database configuration (passed via DI)
            optimizer_state: Shared state for tracking optimizer success/failure
            target_metric: Optimization mode (whole-repo vs targeted validation)
            budget_limit: Dollar budget limit for optimization
            workspace_manager: Workspace manager for agent workspace paths
            snapshot_slugs: Train snapshots to hydrate and mount
            verbose: Verbose output flag
        """
        # Store parameters for server factory and external access
        self._optimizer_run_id = optimizer_run_id
        self._critic_client = critic_client
        self._grader_client = grader_client
        self._db_config = db_config
        self.optimizer_state = optimizer_state  # Exposed for abort checking
        self._target_metric = target_metric
        self._budget_limit = budget_limit
        self._verbose = verbose

        super().__init__(
            definition_id=PROMPT_OPTIMIZER_AGENT_DEFINITION_ID,
            agent_run_id=optimizer_run_id,
            docker_client=docker_client,
            hydrator=hydrator,
            db_config=db_config,
            workspace_manager=workspace_manager,
            snapshot_slugs=snapshot_slugs,
        )

    @property
    def type_config(self) -> PromptOptimizerTypeConfig:
        """Get the type config for creating the AgentRun record."""
        return PromptOptimizerTypeConfig(target_metric=self._target_metric)

    def _make_mcp_server(self, auth: AuthProvider) -> EnhancedFastMCP:
        """Create prompt eval server.

        Args:
            auth: Auth provider for HTTP authentication (unused - server doesn't use auth)

        Returns:
            PromptEvalServer with prompt optimization tools
        """
        server = PromptEvalServer(
            critic_client=self._critic_client,
            grader_client=self._grader_client,
            docker_client=self._docker_client,
            hydrator=self._hydrator,
            db_config=self._db_config,
            workspace_manager=self._workspace_manager,
            optimizer_state=self.optimizer_state,
            target_metric=self._target_metric,
            optimizer_run_id=self._optimizer_run_id,
            workspace_root=self.workspace_root,
            budget_limit=self._budget_limit,
            verbose=self._verbose,
        )
        # Store reference for programmatic access (bootstrap introspection)
        self.prompt_eval_server = server
        return server


# ============================================================================
# MCP Server for Prompt Evaluation
# ============================================================================


# --- MCP Tool Input Types ---


class CreateCriticDefinitionInput(OpenAIStrictModeBaseModel):
    """Input for create_critic_definition tool.

    Creates a new critic agent definition from a directory containing:
    - AGENT.md: System prompt for the critic
    - init: Executable bootstrap script (must be chmod +x)

    The directory is packed into a tar archive and stored in the database.
    Returns a definition_id that can be used with run_critic.
    """

    definition_dir: str = Field(
        description="Path to definition directory in container (e.g., /workspace/critic-v1/). "
        "Must contain AGENT.md and executable init script."
    )


class CreateCriticDefinitionOutput(OpenAIStrictModeBaseModel):
    """Output for create_critic_definition tool."""

    definition_id: str = Field(description="ID of the created agent definition. Use this with run_critic.")
    message: str = Field(description="Success message with details about the created definition.")


class RunCriticInput(OpenAIStrictModeBaseModel):
    """Run critic using an agent definition.

    Returns critic_run_id for subsequent grading.

    Mode-specific restrictions (enforced by RLS + MCP):
    - Whole-Repo Mode: VALID split requires scope_hash for entire-snapshot examples only
    - Targeted Mode: VALID split allows scope_hash for both per-file and entire-snapshot examples
    - TRAIN split: All example scope_hash values allowed in all modes

    Query the examples table to find valid (snapshot_slug, scope_hash) pairs:
    SELECT snapshot_slug, scope_hash, scope FROM examples WHERE snapshot_slug='...'
    """

    definition_id: str = Field(
        description="Agent definition ID (from create_critic_definition or 'critic' for baseline)"
    )
    snapshot_slug: SnapshotSlug = Field(description="Snapshot slug (e.g., ducktape/2025-11-26-00)")
    scope_hash: str = Field(
        description="Example scope hash (64-char hex string) - identifies which files to review. "
        "Query examples table to find valid scope_hash values for a snapshot."
    )
    max_turns: int = Field(ge=200, le=200, description="Maximum sampling turns (fixed at 200)")


class RunCriticOutput(OpenAIStrictModeBaseModel):
    """Output for run_critic tool - DB ID for critic run."""

    critic_run_id: UUID = Field(
        description="agent_run_id of the critic agent run. Query agent_runs for output, costs, model. Pass to run_grader to grade against ground truth."
    )
    # cumulative_cost_usd: float = Field(
    #     description="Total cumulative cost (USD) for all critic/grader runs in this optimization session so far."
    # )


class RunGraderInput(OpenAIStrictModeBaseModel):
    """Input for run_grader tool.

    Note: model is NOT included - the server is bound to a specific client/model at build time.
    """

    critic_run_id: UUID = Field(description="agent_run_id of the critic agent run to grade (from run_critic output)")
    max_turns: int = Field(ge=200, le=200, description="Maximum sampling turns (fixed at 200)")


class RunGraderOutput(OpenAIStrictModeBaseModel):
    """Output for run_grader tool - DB ID and instructions for querying metrics."""

    grader_run_id: UUID = Field(description="agent_run_id of the grader agent run. Run has been saved to database.")
    message: str = Field(
        description="Instructions for querying recall metrics from database views (aggregated across runs)."
    )
    # cumulative_cost_usd: float = Field(
    #     description="Total cumulative cost (USD) for all critic/grader runs in this optimization session so far."
    # )


class PromptEvalServer(EnhancedFastMCP):
    """Prompt eval MCP server with typed resource/tool access.

    Tool name constants (SSOT for tests):
    - CREATE_CRITIC_DEFINITION_TOOL = "create_critic_definition"
    - RUN_CRITIC_TOOL = "run_critic"
    - RUN_GRADER_TOOL = "run_grader"

    Provides MCP tools for definition-based critic optimization:
    - create_critic_definition(definition_dir) -> definition_id
    - run_critic(definition_id, snapshot_slug, scope_hash) -> critic_run_id
    - run_grader(critic_run_id) -> grader_run_id

    Tools return only DB IDs. Agent queries database for results, metrics, costs.

    TODO: Implement proper cost tracking and limiting
    TODO: Add max wall time constraint for critic runs (5 minutes)
    TODO: Consider system message anti-repetition hook
    """

    # Tool name constants (SSOT for tests)
    CREATE_CRITIC_DEFINITION_TOOL = "create_critic_definition"
    RUN_CRITIC_TOOL = "run_critic"
    RUN_GRADER_TOOL = "run_grader"

    # Tool references (assigned in __init__)
    create_critic_definition_tool: FunctionTool
    run_critic_tool: FunctionTool
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
        workspace_manager: WorkspaceManager,
        optimizer_state: PromptOptimizerState,
        target_metric: TargetMetric,
        optimizer_run_id: UUID,
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
            workspace_manager: Workspace manager for agent workspace paths
            optimizer_state: Shared state for tracking optimizer success/failure
            target_metric: Optimization mode (whole-repo vs targeted validation)
            optimizer_run_id: ID of the optimizer agent run for tracking prompts
            workspace_root: Working directory for reading prompt files
            budget_limit: Dollar budget limit for optimization (currently not enforced)
            verbose: Verbose output flag
        """
        super().__init__(
            "prompt_eval",
            instructions=(
                "Agent definition optimization tools: "
                "create_critic_definition(definition_dir) - pack a critic definition directory into database, "
                "run_critic(definition_id, snapshot_slug, scope_hash) - run critic agent, "
                "run_grader(critic_run_id) - grade critiques against ground truth. "
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
        self._workspace_manager = workspace_manager
        self._optimizer_state = optimizer_state
        self._target_metric = target_metric
        self._optimizer_run_id = optimizer_run_id
        self._workspace_root = workspace_root
        self._budget_limit = budget_limit
        self._verbose = verbose

        # Note: Agent run ID is available via current_agent_run_id() SQL function
        # which extracts it from the database username pattern (agent_{uuid}).

        # Register tools - names derived from function names
        async def create_critic_definition(payload: CreateCriticDefinitionInput) -> CreateCriticDefinitionOutput:
            """Create a new critic agent definition from a directory.

            The directory must contain:
            - AGENT.md: System prompt for the critic (review instructions, strategy, etc.)
            - init: Executable bootstrap script (chmod +x, runs before critic starts)

            Creates definition directory structure:
            1. Use docker_exec to mkdir and create files (AGENT.md, init)
            2. chmod +x the init script
            3. Call this tool with the directory path

            Example workflow:
                # Create definition directory
                docker_exec: mkdir -p /workspace/critic-v1

                # Write AGENT.md (system prompt)
                docker_exec: cat > /workspace/critic-v1/AGENT.md << 'EOF'
                # Code Review Critic
                You are a code reviewer...
                EOF

                # Write init script
                docker_exec: cat > /workspace/critic-v1/init << 'EOF'
                #!/bin/bash
                echo "Critic agent starting..."
                EOF

                # Make init executable
                docker_exec: chmod +x /workspace/critic-v1/init

                # Create definition and get ID
                create_critic_definition(definition_dir="/workspace/critic-v1")
            """
            # Map container path to host path
            container_path = Path(payload.definition_dir)
            try:
                relative_path = container_path.relative_to(WORKING_DIR)
            except ValueError:
                raise ToolError(f"Definition directory must be under {WORKING_DIR}/, got: {payload.definition_dir}")

            host_path = workspace_root / relative_path

            if not host_path.is_dir():
                raise ToolError(
                    f"Definition directory not found or not a directory: {payload.definition_dir}. "
                    f"First create the directory and required files (AGENT.md, init) using docker_exec."
                )

            # Validate definition structure
            errors = validate_definition(host_path)
            if errors:
                error_list = "\n".join(f"  - {e}" for e in errors)
                raise ToolError(
                    f"Invalid agent definition:\n{error_list}\n\n"
                    f"Required structure:\n"
                    f"  {payload.definition_dir}/\n"
                    f"    AGENT.md   (system prompt)\n"
                    f"    init       (executable bootstrap script)"
                )

            # Generate definition ID
            definition_id = f"critic_{uuid4().hex[:12]}"

            # Pack definition into tar archive (resolve_symlinks=False for security)
            try:
                archive = pack_definition(host_path, resolve_symlinks=False)
            except ValueError as e:
                raise ToolError(str(e)) from e

            # Insert into database
            with get_session() as session:
                definition = AgentDefinition(
                    id=definition_id,
                    agent_type=AgentType.CRITIC.value,
                    archive=archive,
                    created_by_agent_run_id=optimizer_run_id,
                )
                session.add(definition)
                session.commit()

            return CreateCriticDefinitionOutput(
                definition_id=definition_id,
                message=(
                    f"Created critic definition: {definition_id}. "
                    f"Archive size: {len(archive):,} bytes. "
                    f"Use this ID with run_critic."
                ),
            )

        self.create_critic_definition_tool = self.flat_model()(create_critic_definition)

        async def run_critic(payload: RunCriticInput) -> RunCriticOutput:
            """Run critic agent using an agent definition.

            Loads critic definition from database (AGENT.md, init script) and runs
            the critic on the specified snapshot/scope.

            Validates split-based access restrictions:
            - TRAIN split: all scopes allowed
            - VALID split: only entire_snapshot scope allowed (no per-file examples)
            - TEST split: completely off-limits

            Returns critic_run_id for subsequent grading with run_grader.
            """
            # Validate definition exists
            with get_session() as session:
                definition = session.get(AgentDefinition, payload.definition_id)
                if not definition:
                    raise ToolError(
                        f"Agent definition not found: {payload.definition_id}. "
                        f"Use create_critic_definition to create a new definition first."
                    )

                # Load and validate snapshot
                db_snapshot = session.query(Snapshot).filter_by(slug=payload.snapshot_slug).one_or_none()
                if not db_snapshot:
                    raise ToolError(f"Snapshot {payload.snapshot_slug} not found")

                # Validate split-based access restrictions
                if db_snapshot.split == Split.TEST:
                    raise ToolError(
                        f"Access denied: 'test' split is completely off-limits. "
                        f"You can only run evaluations on 'train' and 'valid' splits. "
                        f"Snapshot {payload.snapshot_slug} is in 'test' split."
                    )

                # Look up example by (snapshot_slug, scope_hash)
                example = (
                    session.query(Example)
                    .filter_by(snapshot_slug=payload.snapshot_slug, scope_hash=payload.scope_hash)
                    .one_or_none()
                )

                if not example:
                    # List available examples for this snapshot
                    available = session.query(Example).filter_by(snapshot_slug=payload.snapshot_slug).all()
                    example_list = "\n".join(
                        f"  - scope_hash={ex.scope_hash[:16]}... scope={ex.scope}" for ex in available[:10]
                    )
                    if len(available) > 10:
                        example_list += f"\n  ... and {len(available) - 10} more"

                    raise ToolError(
                        f"No example found with scope_hash={payload.scope_hash} in snapshot {payload.snapshot_slug}.\n"
                        f"Available examples ({len(available)} total):\n{example_list}\n\n"
                        f"Query the examples table to find valid (snapshot_slug, scope_hash) pairs:\n"
                        f"SELECT snapshot_slug, scope_hash, scope FROM examples WHERE snapshot_slug='{payload.snapshot_slug}';"
                    )

                # Get scope from example
                scope = example.scope

                # Check if this is a per-file example (ExplicitFileScope) or whole-snapshot (AllFilesScope)
                is_per_file = isinstance(scope, ExplicitFileScope)

                # Check VALID scope restrictions based on target metric mode
                if db_snapshot.split == Split.VALID and is_per_file and self._target_metric == TargetMetric.WHOLE_REPO:
                    raise ToolError(
                        f"valid split in whole-repo mode requires entire-snapshot examples only. "
                        f"You requested scope_hash={payload.scope_hash} which is a per-file example. "
                        f"Query for whole-snapshot examples: "
                        f"SELECT scope_hash FROM examples WHERE snapshot_slug='{payload.snapshot_slug}' "
                        f"AND (scope->>'kind')='entire_snapshot';"
                    )

            # Execute critic run using definition-based run_critic
            try:
                (critic_run_id, status) = await execute_critic_run(
                    definition_id=payload.definition_id,
                    snapshot_slug=payload.snapshot_slug,
                    scope=scope,
                    client=self._critic_client,
                    parent_agent_run_id=self._optimizer_run_id,
                    docker_client=self._docker_client,
                    hydrator=self._hydrator,
                    db_config=self._db_config,
                    workspace_manager=self._workspace_manager,
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

            # Check status to provide specific error messages
            if status == AgentRunStatus.MAX_TURNS_EXCEEDED:
                raise ToolError(
                    f"Critic agent exceeded maximum turns ({payload.max_turns}).\n\n"
                    f"{_AGENT_STUCK_ADVICE}\n"
                    f"{_trace_query_advice(run_id=critic_run_id)}"
                )
            if status == AgentRunStatus.CONTEXT_LENGTH_EXCEEDED:
                raise ToolError(
                    f"Critic agent exceeded context length.\n\n"
                    f"{_AGENT_STUCK_ADVICE}\n"
                    f"{_trace_query_advice(run_id=critic_run_id)}"
                )

            # At this point status must be COMPLETED
            return RunCriticOutput(critic_run_id=critic_run_id)

        self.run_critic_tool = self.flat_model()(run_critic)

        async def run_grader(payload: RunGraderInput) -> RunGraderOutput:
            """Run grader agent to evaluate a critique against ground truth.

            Saves grader run to database with per-occurrence credits.

            To get recall metrics, query aggregate views (see system_overview.md for details):
            - aggregated_recall_by_definition: Recall per (agent_definition_id, models, split)
            - aggregated_recall_by_example: Recall per (example, models, split)

            Returns grader_run_id and instructions for querying metrics.
            """
            # Execute GraderRun by critic_run_id (fetches critic run from DB, saves grader run to DB)
            with get_session() as session:
                try:
                    grader_run_id = await grade_critic_run_by_id(
                        session=session,
                        critic_run_id=payload.critic_run_id,
                        client=self._grader_client,
                        docker_client=self._docker_client,
                        hydrator=self._hydrator,
                        db_config=self._db_config,
                        workspace_manager=self._workspace_manager,
                        parent_agent_run_id=self._optimizer_run_id,
                        verbose=self._verbose,
                        max_turns=payload.max_turns,
                    )
                except (GraderDidNotSubmitError, MaxTurnsExceededError) as e:
                    # Try to find grader_run_id for better error messages
                    # (grader run is created in DB even if execution fails)
                    # Query AgentRun where type_config.graded_agent_run_id matches critic_run_id
                    failed_grader_run = (
                        session.query(AgentRun)
                        .filter(AgentRun.type_config["graded_agent_run_id"].astext == str(payload.critic_run_id))
                        .order_by(AgentRun.created_at.desc())
                        .first()
                    )
                    failed_grader_run_id = failed_grader_run.agent_run_id if failed_grader_run else None

                    if isinstance(e, GraderDidNotSubmitError):
                        raise ToolError(
                            f"Grader agent did not call submit(): {e}\n\n"
                            f"{_AGENT_STUCK_ADVICE}\n"
                            f"{_trace_query_advice(critic_run_id=payload.critic_run_id, run_id=failed_grader_run_id, is_grader=True)}"
                        ) from e
                    # MaxTurnsExceededError
                    raise ToolError(
                        f"Grader agent exceeded maximum turns ({payload.max_turns}): {e}\n\n"
                        f"{_AGENT_STUCK_ADVICE}\n"
                        f"{_trace_query_advice(critic_run_id=payload.critic_run_id, run_id=failed_grader_run_id, is_grader=True)}"
                    ) from e

                # Verify grader run succeeded
                # Note: grader_run_id is always UUID here - the except block always raises
                assert grader_run_id is not None
                grader_run = session.get(AgentRun, grader_run_id)
                if not grader_run:
                    raise ToolError(f"Grader run {grader_run_id} not found in database")
                if grader_run.status != AgentRunStatus.COMPLETED:
                    raise ToolError(
                        f"Grader run {grader_run_id} did not complete successfully (status={grader_run.status.value})\n\n"
                        f"{_AGENT_STUCK_ADVICE}\n"
                        f"{_trace_query_advice(critic_run_id=payload.critic_run_id, run_id=grader_run_id, is_grader=True)}"
                    )

                # Determine split and whether this is a full-snapshot run
                # Get snapshot_slug from the graded critic run
                graded_critic_run_id = grader_run.grader_config().graded_agent_run_id
                critic_run = session.get(AgentRun, graded_critic_run_id)
                if not critic_run:
                    raise ToolError(f"Grader run {grader_run_id} has no associated critic run")
                critic_config = critic_run.critic_config()
                snapshot_slug = critic_config.snapshot_slug
                snapshot = session.query(Snapshot).filter_by(slug=snapshot_slug).one()
                split = snapshot.split

                # Find matching example to check scope kind
                critic_scope_hash = critic_config.scope_hash
                example = (
                    session.query(Example)
                    .filter_by(snapshot_slug=snapshot_slug, scope_hash=critic_scope_hash)
                    .one()  # Raise if not found - this is a data integrity error
                )

                scope_kind = (
                    ScopeKind.ENTIRE_SNAPSHOT if isinstance(example.scope, AllFilesScope) else ScopeKind.SPECIFIC_FILES
                )

                # Compute immediate feedback from this grader run (direct query to grading_decisions)
                # Pattern 1: Total credit (recall numerator)
                total_credit = (
                    session.query(func.sum(GradingDecision.credit))
                    .filter_by(agent_run_id=grader_run_id)
                    .filter(GradingDecision.target_tp_id.isnot(None))  # Only TP matches
                    .scalar()
                    or 0.0
                )

                # Pattern 2: Occurrence count (recall denominator)
                max_credit = (
                    session.query(GradingDecision.target_tp_id, GradingDecision.target_tp_occurrence_id)
                    .filter_by(agent_run_id=grader_run_id)
                    .filter(GradingDecision.target_tp_id.isnot(None))
                    .distinct()
                    .count()
                )

                # Build message with immediate feedback and query advice
                immediate_feedback = (
                    f"Grader run {grader_run_id} completed successfully. "
                    f"Total credit: {total_credit:.2f} of {max_credit}. "
                )

                # Add query advice based on split, example type, and optimization mode
                if (
                    split == Split.VALID
                    and scope_kind == ScopeKind.ENTIRE_SNAPSHOT
                    and self._target_metric == TargetMetric.WHOLE_REPO
                ):
                    # VALID full-snapshot in whole-repo mode: use validation function
                    query_advice = (
                        f"{_FUNCTION_BASED_METRICS_ADVICE} "
                        f"Example: SELECT * FROM {_VALIDATION_FUNCTION_NAME} WHERE grader_run_id = '{grader_run_id}'; "
                        f"For full details: SELECT * FROM agent_runs WHERE agent_run_id = '{grader_run_id}';"
                    )
                elif (
                    split == Split.VALID
                    and scope_kind == ScopeKind.ENTIRE_SNAPSHOT
                    and self._target_metric == TargetMetric.TARGETED
                ):
                    # VALID full-snapshot in targeted mode: use aggregate views
                    query_advice = (
                        f"{_VIEW_BASED_METRICS_ADVICE} "
                        "IMPORTANT: Check n_examples >= 5 before trusting metrics (small samples have high variance). "
                        "Use UCB/LCB bounds to quantify uncertainty. "
                        f"Example: SELECT recall, n_examples, ucb, lcb FROM aggregated_recall_by_definition "
                        f"WHERE agent_definition_id='...' AND split='valid' AND scope_kind='{ScopeKind.ENTIRE_SNAPSHOT}'; "
                        f"For full details: SELECT * FROM agent_runs WHERE agent_run_id = '{grader_run_id}';"
                    )
                else:
                    # TRAIN split or per-file examples: use aggregate views
                    query_advice = (
                        f"{_VIEW_BASED_METRICS_ADVICE} "
                        "Example: SELECT recall FROM aggregated_recall_by_definition WHERE agent_definition_id='...' AND split='train'; "
                        f"For full details: SELECT * FROM agent_runs WHERE agent_run_id = '{grader_run_id}';"
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
    hydrator: SnapshotHydrator,
    optimizer_client: OpenAIModelProto,
    critic_client: OpenAIModelProto,
    grader_client: OpenAIModelProto,
    docker_client: aiodocker.Docker,
    target_metric: TargetMetric,
    db_config: DatabaseConfig,
    verbose: bool = False,
    max_lines: int = DEFAULT_MAX_LINES,
) -> None:
    """Run a Prompt Engineering agent to optimize a critic system prompt.

    Args:
        budget: Dollar budget for optimization
        hydrator: Snapshot hydrator for source code extraction
        optimizer_client: OpenAI client for prompt optimizer agent
        critic_client: OpenAI client for running critic evaluations
        grader_client: OpenAI client for running grader evaluations
        docker_client: Async Docker client for container operations
        target_metric: Optimization mode (whole-repo vs targeted validation)
        db_config: Database configuration for temp user creation and queries
        verbose: Verbose output flag
        max_lines: Maximum lines for formatting tool responses

    Hydrates train snapshots and mounts them with definitions via Docker.
    The agent can query train data and valid aggregates via database (temporary user with RLS).
    """
    # Get train snapshots from database
    with get_session() as session:
        train_snapshots = session.query(Snapshot).filter_by(split=Split.TRAIN.value).all()
        train_slugs = [SnapshotSlug(s.slug) for s in train_snapshots]

    logger.info(f"Will mount {len(train_slugs)} train snapshots (compositor will handle hydration)")

    # Generate unique ID for this run
    agent_run_id = uuid4()
    logger.info(f"Prompt optimizer agent_run_id: {agent_run_id}")

    # Phase 1: Write initial AgentRun to DB (BEFORE agent runs - FK constraint!)
    with get_session() as session:
        # Build type_config for prompt optimizer using Pydantic model
        type_config = PromptOptimizerTypeConfig(target_metric=target_metric).model_dump()
        # Add additional config fields
        type_config["budget_limit"] = budget
        type_config["optimizer_model"] = optimizer_client.model
        type_config["critic_model"] = critic_client.model
        type_config["grader_model"] = grader_client.model

        agent_run = AgentRun(
            agent_run_id=agent_run_id,
            agent_definition_id=PROMPT_OPTIMIZER_AGENT_DEFINITION_ID,
            model=optimizer_client.model,
            type_config=type_config,
            status=AgentRunStatus.IN_PROGRESS,
        )
        session.add(agent_run)
        session.commit()

    logger.info(f"Created prompt optimizer AgentRun: {agent_run_id}")

    # Create agent environment with prompt eval HTTP MCP server and temporary user
    # AgentEnvironment creates temporary database user with TRAIN-split-only access
    # AgentEnvironment handles snapshot hydration, HTTP server, and container lifecycle
    workspace_manager = WorkspaceManager.from_env()
    agent_env = PromptOptimizerAgentEnvironment(
        docker_client=docker_client,
        hydrator=hydrator,
        optimizer_run_id=agent_run_id,
        critic_client=critic_client,
        grader_client=grader_client,
        db_config=db_config,
        optimizer_state=PromptOptimizerState(),
        target_metric=target_metric,
        budget_limit=budget,
        workspace_manager=workspace_manager,
        snapshot_slugs=train_slugs,  # AgentEnvironment will hydrate and mount these automatically
        verbose=verbose,
    )
    async with agent_env as comp:
        # comp is a PropertiesDockerCompositor with:
        # - comp.runtime (Docker exec server)
        # - HTTP MCP server with prompt_eval tools (accessed via MCP client)

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

        def _optimizer_should_abort() -> bool:
            """Check if optimizer reported failure."""
            return agent_env.optimizer_state.error is not None

        # Build handlers for prompt optimizer agent
        # NOTE: Do NOT call build_props_handlers() here - AgentHandle.create() already adds
        # DatabaseEventHandler. We only add CompactDisplayHandler if verbose is enabled.
        handlers: list = []
        if verbose:
            display_handler = await CompactDisplayHandler.from_compositor(
                comp, max_lines=max_lines, prefix=f"[OPTIMIZER:{short_uuid(agent_run_id)}] "
            )
            handlers.append(display_handler)

        handlers.extend(
            [
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
        )

        # Note: resources and compositor_meta are auto-mounted by base Compositor
        async with Client(comp) as mcp_client:
            # Create agent handle - handles definition loading, workspace, init script, system prompt
            handle = await AgentHandle.create(
                agent_run_id=agent_run_id,
                definition_id=PROMPT_OPTIMIZER_AGENT_DEFINITION_ID,
                model_client=optimizer_client,
                mcp_client=mcp_client,
                compositor=comp,
                workspace_manager=workspace_manager,
                handlers=handlers,
                parallel_tool_calls=True,
                reasoning_summary=ReasoningSummary.detailed,
            )

            # Add budget enforcement handler after agent creation (needs agent reference)
            budget_handler = BudgetEnforcementHandler(
                optimizer_run_id=agent_run_id, budget_limit=budget, agent=handle.agent
            )
            handle.agent._handlers.append(budget_handler)

            handle.insert_message(UserMessage.text(user))
            logger.debug("Starting agent.run()")
            await handle.run()
            logger.debug("Agent run complete")
    # Compositor.__aexit__ unmounts all non-pinned servers and cleans up containers here

    logger.info("Optimization session complete.")
    logger.info(f"Budget: ${budget:.2f}")

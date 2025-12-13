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

from __future__ import annotations

from contextlib import AsyncExitStack
import logging
from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from adgn.mcp.resources.server import ResourcesServer

import aiodocker
from fastmcp.client import Client
from fastmcp.exceptions import ToolError
from fastmcp.resources import FunctionResource
from fastmcp.tools import FunctionTool
from pydantic import Field

from adgn.agent.agent import Agent
from adgn.agent.bootstrap import TypedBootstrapBuilder, read_package_file_call, read_resource_call
from adgn.agent.handler import RedirectOnTextMessageHandler, SequenceHandler
from adgn.agent.loop_control import AllowAnyToolOrTextMessage, InjectItems
from adgn.agent.turn_limit import MaxTurnsExceededError
from adgn.mcp._shared.constants import WORKING_DIR
from adgn.mcp._shared.mounted import Mounted
from adgn.mcp._shared.types import MCPMountPrefix
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.mcp.exec.docker.server import ContainerExecServer
from adgn.openai_utils.model import FunctionCallItem, OpenAIModelProto, SystemMessage, UserMessage
from adgn.openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel
from adgn.openai_utils.types import ReasoningSummary
from adgn.props.agent_setup import build_props_handlers
from adgn.props.cli.common_options import DEFAULT_MAX_LINES
from adgn.props.critic.critic import run_critic as execute_critic_run
from adgn.props.critic.exceptions import CriticDidNotSubmitError, CriticExecutionError
from adgn.props.critic.models import CriticInput
from adgn.props.db import get_session, query_builders as qb
from adgn.props.db.config import DbConnectionConfig, get_production_config
from adgn.props.db.models import Example, GraderRun as DBGraderRun, PromptOptimizationRun, Snapshot
from adgn.props.db.prompts import hash_and_upsert_prompt
from adgn.props.db.snapshots import DBGraderSuccess
from adgn.props.display import short_uuid
from adgn.props.docker_env import PROPS_NETWORK_NAME, PropertiesDockerCompositor
from adgn.props.grader.exceptions import GraderDidNotSubmitError
from adgn.props.grader.grader import grade_critique_by_id
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import ExplicitFileScope
from adgn.props.prompt_optimize.budget_handler import BudgetEnforcementHandler
from adgn.props.prompts.util import render_prompt_template
from adgn.props.prop_utils import specimens_definitions_root
from adgn.props.runs_context import RunsContext, format_timestamp_session
from adgn.props.splits import Split

logger = logging.getLogger(__name__)


# Common error message advice
_AGENT_STUCK_ADVICE = (
    "Agent exceeded turn limit. This could mean:\n"
    "  1. Agent needed more turns to complete the task (reading files, analyzing code, etc.)\n"
    "  2. Agent stuck in a loop or not following instructions\n"
    "  3. Agent ran out of tokens\n"
    "Check the transcript in the database to determine if the agent was making productive progress or stuck."
)


def _trace_query_advice(*, snapshot_slug: str | None = None, critique_id: str | None = None) -> str:
    """Generate advice for querying execution traces.

    Exactly one of snapshot_slug or critique_id must be provided.
    """
    if snapshot_slug is not None and critique_id is None:
        tables = "critic_runs and events"
        condition = f"snapshot_slug='{snapshot_slug}'"
    elif critique_id is not None and snapshot_slug is None:
        tables = "grader_runs and events"
        condition = f"critique_id='{critique_id}'"
    else:
        raise ValueError("Exactly one of snapshot_slug or critique_id must be provided")

    return f"Query {tables} tables for {condition} to see execution trace."


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
    prompt_eval: Mounted[PromptEvalServer],
) -> list[FunctionCallItem]:
    """Build bootstrap calls: reads PO run ID, critic template, example query scripts, and research docs.

    Args:
        builder: Bootstrap builder for generating typed tool calls
        resources: Mounted resources server (comp.resources)
        runtime: Mounted runtime server (comp.runtime)
        prompt_eval: Mounted prompt eval server
    """
    return [
        # System overview (snapshots, database, critic architecture, evaluation flow)
        *_read_package_files(builder, runtime, "adgn.props.docs", ["system_overview.md"]),
        # Prompt optimization run ID
        read_resource_call(
            builder,
            resources,
            server=prompt_eval.prefix,
            uri=prompt_eval.server.optimization_run_id_resource.uri,
            max_bytes=256,
        ),
        # Critic template structure
        *_read_package_files(builder, runtime, "adgn.props.critic", ["prompts/critic_system.j2.md"]),
        # Database query examples
        *_read_package_files(
            builder,
            runtime,
            "adgn.props.examples",
            [
                "query_top_prompts.py",
                "query_train_examples.py",
                "query_full_snapshot_train_examples.py",
                "query_valid_examples.py",
                "query_run_status.py",
                "query_execution_traces.py",
                "query_train_vs_valid_performance.py",
            ],
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
    """Compositor with prompt optimizer servers pre-mounted.

    Inherits from PropertiesDockerCompositor, which provides:
    - runtime: Docker exec server (mounted by parent class)

    Adds:
    - prompt_eval: Prompt evaluation server (critic/grader orchestration)

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
    prompt_eval: Mounted[PromptEvalServer]

    def __init__(
        self,
        workspace_root: Path,
        docker_client: aiodocker.Docker,
        *,
        critic_client: OpenAIModelProto,
        grader_client: OpenAIModelProto,
        hydrator: SnapshotHydrator,
        prompt_optimization_run_id: UUID,
        budget_limit: float,
        verbose: bool = False,
        db_conn: DbConnectionConfig | None = None,
        network_mode: str = PROPS_NETWORK_NAME,
    ):
        """Create compositor with prompt optimization dependencies.

        Args:
            workspace_root: Path to workspace directory to mount in container.
            docker_client: Async Docker client (managed by caller).
            critic_client: OpenAI client for running critic evaluations
            grader_client: OpenAI client for running grader evaluations
            hydrator: Snapshot hydrator for source code extraction
            prompt_optimization_run_id: ID of the optimization run for tracking prompts
            budget_limit: Dollar budget limit for optimization
            verbose: Verbose output flag
            db_conn: Optional database connection config for container (required for PO agent)
            network_mode: Docker network mode (default: PROPS_NETWORK_NAME for database access)

        Note:
            workspace_mode, ephemeral, mount_properties, extra_binds, and extra_env are fixed and NOT overridable.
        """
        # Always pass fixed parameters to parent
        super().__init__(
            workspace_root,
            docker_client,
            workspace_mode="rw",
            ephemeral=False,
            mount_properties=False,
            db_conn=db_conn,
            network_mode=network_mode,
        )

        # Store PromptEvalServer parameters
        self._critic_client = critic_client
        self._grader_client = grader_client
        self._docker_client = docker_client
        self._hydrator = hydrator
        self._prompt_optimization_run_id = prompt_optimization_run_id
        self._workspace_root = workspace_root
        self._budget_limit = budget_limit
        self._verbose = verbose

    async def __aenter__(self):
        """Start compositor and mount servers."""
        # Start parent compositor (mounts resources, compositor_meta, runtime)
        await super().__aenter__()

        # Mount prompt eval server with individual parameters
        self.prompt_eval = await self.mount_inproc(
            "prompt_eval",
            PromptEvalServer(
                critic_client=self._critic_client,
                grader_client=self._grader_client,
                docker_client=self._docker_client,
                hydrator=self._hydrator,
                name="prompt_eval",
                prompt_optimization_run_id=self._prompt_optimization_run_id,
                workspace_root=self._workspace_root,
                budget_limit=self._budget_limit,
                verbose=self._verbose,
            ),
            pinned=True,
        )

        return self


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
    """Run critic on a specific example from database.

    Examples are pre-defined file sets from the examples table representing
    training datapoints. Each example has a composite key (snapshot_slug, files_hash).

    Query available examples:
      SELECT snapshot_slug, files_hash, files, array_length(files, 1) as file_count
      FROM examples e
      JOIN snapshots s ON e.snapshot_slug = s.slug
      WHERE s.split = 'train'
      ORDER BY snapshot_slug, files_hash;
    """

    snapshot_slug: SnapshotSlug = Field(description="Snapshot slug (e.g., ducktape/2025-11-26-00)")
    files_hash: str = Field(description="SHA256 hash identifying the file set (from examples table)")
    prompt_sha256: str = Field(description="SHA256 hash of the system prompt (from upsert_prompt)")
    max_turns: int = Field(ge=1, lt=300, description="Maximum sampling turns. Recommended: 100")


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
    max_turns: int = Field(
        ge=1, lt=1000, description="Maximum number of sampling turns allowed for this grader run (1-999)"
    )


class RunGraderOutput(OpenAIStrictModeBaseModel):
    """Output for run_grader tool - DB ID and measured recall."""

    grader_run_id: UUID = Field(description="grader_runs.id - Query grader_runs table for full output.")
    recall: float = Field(description="Measured recall for this critique (0.0-1.0)")
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
    - run_critic_on_example(snapshot_slug, files_hash, prompt_sha256) -> critic_run_id, critique_id
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

    def __init__(
        self,
        *,
        critic_client: OpenAIModelProto,
        grader_client: OpenAIModelProto,
        docker_client: aiodocker.Docker,
        hydrator: SnapshotHydrator,
        name: str = "prompt_eval",
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
            name: MCP server name
            prompt_optimization_run_id: ID of the optimization run for tracking prompts
            workspace_root: Working directory for reading prompt files
            budget_limit: Dollar budget limit for optimization (currently not enforced)
            verbose: Verbose output flag
        """
        super().__init__(
            name,
            instructions=(
                "Prompt optimization tools: save prompts to database (upsert_prompt), "
                "run critic agents on training examples (run_critic_on_example), "
                "grade critiques against ground truth (run_grader). "
                "Query the database for results, costs, and metrics."
            ),
        )

        # Store parameters for use in tools
        self._critic_client = critic_client
        self._grader_client = grader_client
        self._docker_client = docker_client
        self._hydrator = hydrator
        self._prompt_optimization_run_id = prompt_optimization_run_id
        self._workspace_root = workspace_root
        self._budget_limit = budget_limit
        self._verbose = verbose

        # Register resource and stash the result
        async def get_prompt_optimization_run_id() -> str:
            """Get the prompt optimization run ID for this session.

            Use this UUID to query costs via qb.po_run_costs(po_run_id) from db.query_builders.
            """
            return str(prompt_optimization_run_id)

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
            """Run critic on a pre-defined example from the examples table.

            Examples are auto-generated training datapoints with validated file sets.
            Use (snapshot_slug, files_hash) composite key to reference a specific example.

            This ensures the critic only runs on meaningful training examples with
            known ground truth coverage.

            Query examples:
              SELECT snapshot_slug, files_hash, files, array_length(files, 1) as file_count
              FROM examples e
              JOIN snapshots s ON e.snapshot_slug = s.slug
              WHERE s.split = 'train'
              ORDER BY snapshot_slug, files_hash;
            """
            # Load and validate example from database
            with get_session() as session:
                example = (
                    session.query(Example)
                    .filter_by(snapshot_slug=payload.snapshot_slug, files_hash=payload.files_hash)
                    .one_or_none()
                )

                if not example:
                    raise ToolError(
                        f"Example not found: snapshot={payload.snapshot_slug}, "
                        f"files_hash={payload.files_hash[:16]}... "
                        f"Query the examples table to find valid examples."
                    )

                # Load snapshot
                db_snapshot = session.query(Snapshot).filter_by(slug=payload.snapshot_slug).one_or_none()
                if not db_snapshot:
                    raise ToolError(f"Snapshot {payload.snapshot_slug} not found")

                # Build CriticInput from example files
                critic_input = CriticInput(
                    snapshot_slug=payload.snapshot_slug,
                    files=ExplicitFileScope(files=example.files),
                    prompt_sha256=payload.prompt_sha256,
                )

            # Hydrate snapshot to get content_root
            async with self._hydrator.hydrate(payload.snapshot_slug) as hydrated:
                # Execute critic run
                try:
                    (_critic_success, critic_run_id, critique_id) = await execute_critic_run(
                        input_data=critic_input,
                        client=self._critic_client,
                        docker_client=self._docker_client,
                        content_root=hydrated.content_root,
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
                except MaxTurnsExceededError as e:
                    raise ToolError(
                        f"Critic agent exceeded maximum turns ({payload.max_turns}): {e}\n\n"
                        f"{_AGENT_STUCK_ADVICE}\n"
                        f"{_trace_query_advice(snapshot_slug=payload.snapshot_slug)}"
                    ) from e

                if critique_id is None:
                    raise ToolError(
                        f"Critic run completed but no critique was created. Query critic_runs with id={critic_run_id}."
                    )

                return RunCriticOutput(critic_run_id=critic_run_id, critique_id=critique_id)

        self.run_critic_on_example_tool = self.flat_model()(run_critic_on_example)

        async def run_grader(payload: RunGraderInput) -> RunGraderOutput:
            """Given a critique produced by a critic, runs a grader agent to grade the critique against ground truth labels.

            Compares what the critic reported against what should have been found (ground truth).
            Computes recall and detailed coverage information.

            Key fields in grader_runs.output JSONB (train split only):
            - grade.recall: Fraction of ground-truth issues found (PRIMARY METRIC - optimize for this!)
            - grade.reported_issue_ratios: Breakdown of what was reported (tp/fp/unlabeled ratios)
            - grade.canonical_tp_coverage: Detailed per-issue coverage information
            - grade.summary: High-level observations from the grader

            Train/Valid Split Access (Anti-Cheating Design):
            We EXPLICITLY let you read everything in train split, but HIDE validation details so you can
            trust that validation metrics aren't gamed.

            - TRAIN: Full access granted. Read all ground truth (true_positives, false_positives tables).
              Query individual grader run details, execution traces, per-issue coverage breakdowns.
              Example: SELECT output->'grade'->>'recall' FROM grader_runs WHERE id = '<grader_run_id>';
              Use this for debugging why prompts succeed or fail on specific issues.

            - VALID: Restricted to prevent overfitting. Ground truth HIDDEN by RLS (true_positives/
              false_positives queries return 0 rows). Individual grader_runs/critiques HIDDEN by RLS.
              Examples table READABLE (allows querying which validation examples exist for evaluation).
              Aggregate metrics visible via valid_metrics view.
              Example: SELECT snapshot_slug, files_hash FROM examples WHERE ... split='valid';
              Example: SELECT snapshot_slug, recall FROM valid_metrics;

            This ensures validation recall is a trustworthy proxy for test performance. You can run
            evaluations on validation examples (via examples table) but cannot inspect ground truth
            or reverse-engineer answers.

            Use validation aggregates to measure generalization performance across all validation specimens.
            """
            # Execute GraderRun by critique_id (fetches critique from DB, saves grader run to DB)
            with get_session() as session:
                try:
                    grader_run_id = await grade_critique_by_id(
                        session=session,
                        critique_id=payload.critique_id,
                        client=self._grader_client,
                        docker_client=self._docker_client,
                        prompt_optimization_run_id=self._prompt_optimization_run_id,
                        verbose=self._verbose,
                        max_turns=payload.max_turns,
                    )
                except GraderDidNotSubmitError as e:
                    raise ToolError(
                        f"Grader agent did not call submit(): {e}\n\n"
                        f"{_AGENT_STUCK_ADVICE}\n"
                        f"{_trace_query_advice(critique_id=str(payload.critique_id))}"
                    ) from e
                except MaxTurnsExceededError as e:
                    raise ToolError(
                        f"Grader agent exceeded maximum turns ({payload.max_turns}): {e}\n\n"
                        f"{_AGENT_STUCK_ADVICE}\n"
                        f"{_trace_query_advice(critique_id=str(payload.critique_id))}"
                    ) from e

                # Query recall from the grader run output
                grader_run = session.get(DBGraderRun, grader_run_id)
                if not grader_run:
                    raise ToolError(f"Grader run {grader_run_id} not found in database")
                if not grader_run.output:
                    raise ToolError(f"Grader run {grader_run_id} has no output")
                if not isinstance(grader_run.output, DBGraderSuccess):
                    raise ToolError(f"Grader run {grader_run_id} exceeded max turns (no recall available)")

                # Access recall directly from DB model
                recall = grader_run.output.recall

            return RunGraderOutput(grader_run_id=grader_run_id, recall=recall)

        self.run_grader_tool = self.flat_model()(run_grader)


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
        out_dir: Optional output directory
        verbose: Verbose output flag
        max_lines: Maximum lines for formatting tool responses

    Hydrates train snapshots and mounts them with definitions via Docker.
    The agent can query train data and valid aggregates via database (agent_user with RLS).
    """
    # Render system prompt with compiled SQL queries from builders
    system = render_prompt_template(
        "prompt_optimize/prompts/prompt_optimizer_system.j2.md",
        sql_list_train=qb.compile_to_sql(qb.list_train_snapshots()),
        sql_list_train_tps=qb.compile_to_sql(qb.list_train_true_positives()),
        sql_list_train_fps=qb.compile_to_sql(qb.list_train_false_positives()),
        sql_count_issues_by_snapshot=qb.compile_to_sql(qb.count_issues_by_snapshot(split="train")),
        sql_recent_graders=qb.compile_to_sql(qb.recent_grader_results(limit=10)),
        sql_valid_agg_view=qb.compile_to_sql(qb.valid_aggregates_view()),
        # Parameterized queries - compile with placeholders for agent to fill in
        sql_critique_for_snapshot=qb.compile_to_sql_with_placeholders(qb.critiques_for_snapshot_parameterized()),
        sql_link_to_prompt=qb.compile_to_sql_with_placeholders(qb.link_grader_to_prompt_parameterized()),
        sql_tools_used=qb.compile_to_sql_with_placeholders(qb.tools_used_by_transcript_parameterized()),
        sql_tool_sequence=qb.compile_to_sql_with_placeholders(qb.tool_sequence_by_transcript_parameterized()),
        sql_failed_tools=qb.compile_to_sql_with_placeholders(qb.failed_tools_by_transcript_parameterized()),
        sql_blocked_valid_critiques=qb.compile_to_sql(qb.blocked_valid_critiques()),
        sql_blocked_valid_grader_runs=qb.compile_to_sql(qb.blocked_valid_grader_runs()),
        sql_blocked_valid_events=qb.compile_to_sql(qb.blocked_valid_events()),
        # Scope queries
        sql_list_train_scopes=qb.compile_to_sql(qb.list_train_scopes()),
        sql_grader_runs_by_scope=qb.compile_to_sql(qb.grader_runs_by_scope_train(limit=10)),
    )

    # Session directory (inline adhoc_run_dir - only called here)
    ts = format_timestamp_session()
    if out_dir is not None:
        session_dir = out_dir.resolve()
    else:
        session_dir = ctx.base_dir / "prompt_optimize" / f"session_{ts}"
        session_dir.mkdir(parents=True, exist_ok=True)
        session_dir = session_dir.resolve()

    # Get train snapshots from database and hydrate them
    with get_session() as session:
        train_snapshots = session.query(Snapshot).filter_by(split=Split.TRAIN.value).all()
        train_slugs = [SnapshotSlug(s.slug) for s in train_snapshots]

    logger.info(f"Hydrating {len(train_slugs)} train snapshots (for direct Docker mount)")

    # Hydrate train snapshots and keep alive for Docker mounting
    snapshot_paths: dict[SnapshotSlug, Path] = {}
    defs_root = specimens_definitions_root()

    async with AsyncExitStack() as stack:
        # Hydrate each train snapshot and keep alive
        for slug in train_slugs:
            hydrated = await stack.enter_async_context(hydrator.hydrate(slug))
            snapshot_paths[slug] = hydrated.content_root
            logger.debug(f"Hydrated {slug} → {hydrated.content_root} (mount as /snapshots/train/{slug})")

        logger.info(f"Definitions available at {defs_root} (mount subdirs as /defs/{{slug}})")

        # Build extra bind mounts for Docker (snapshots + definitions)
        # Format: {host_path: {"bind": container_path, "mode": "ro"|"rw"}}
        # Train snapshots source code (ro) - mount each separately
        extra_binds = {
            str(path.resolve()): {"bind": f"/snapshots/train/{slug}", "mode": "ro"}
            for slug, path in snapshot_paths.items()
        }

        # Ground truth issues (TPs/FPs) are now accessed via database
        # No longer mount libsonnet definitions from filesystem

        # Get database config (fails fast if env vars not set)
        config = get_production_config()
        agent_conn = config.agent_for_container  # Container-to-container access
        logger.info(f"Agent database: host={agent_conn.host}, db={agent_conn.database}, user={agent_conn.user}")

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
                    "session_dir": str(session_dir),
                },
            )
            session.add(po_run)
            session.flush()
            prompt_optimization_run_id = po_run.id
            session.commit()

        logger.info(f"Created PromptOptimizationRun: {prompt_optimization_run_id}")

        # Create compositor with Docker runtime (no /repo mount - would leak test specimen definitions!)
        # workspace_root (session_dir) will be mounted as /workspace (rw mode for agent to write prompts)
        async with PropertiesDockerCompositor(
            workspace_root=session_dir,
            docker_client=docker_client,
            mount_properties=False,  # No property definitions mounted
            extra_binds=extra_binds,
            ephemeral=False,  # Use persistent container to maintain environment
            workspace_mode="rw",  # Agent needs to write prompt iterations
            db_conn=agent_conn,  # Agent-restricted database access (critical for PO agent)
            network_mode=PROPS_NETWORK_NAME,  # Join postgres network for database access
        ) as comp:
            runtime = comp.runtime  # Runtime server already mounted by PropertiesDockerCompositor

            # TODO: Auto-infer prompt_optimization_run_id in MCP server tools instead of manually passing it here
            # The prompt eval server (and grader/critic tools) should be able to auto-detect when they're
            # being called within a PO session context (e.g., via environment variable, session metadata,
            # or resource lookup) rather than requiring manual ID propagation through all tool calls.
            # This would eliminate the need to manually set prompt_optimization_run_id in RunCriticInput
            # and RunGraderInput.

            # Create and mount prompt_eval server
            prompt_eval = await comp.mount_inproc(
                "prompt_eval",
                PromptEvalServer(
                    critic_client=critic_client,
                    grader_client=grader_client,
                    docker_client=docker_client,
                    hydrator=hydrator,
                    name="Prompt Evaluation MCP Server",
                    prompt_optimization_run_id=prompt_optimization_run_id,
                    workspace_root=session_dir,
                    budget_limit=budget,
                    verbose=verbose,
                ),
            )

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
            builder = TypedBootstrapBuilder.for_server(prompt_eval.server)
            bootstrap_calls = make_po_bootstrap_calls(
                builder, resources=comp.resources, runtime=runtime, prompt_eval=prompt_eval
            )
            bootstrap = SequenceHandler([InjectItems(items=bootstrap_calls)])

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

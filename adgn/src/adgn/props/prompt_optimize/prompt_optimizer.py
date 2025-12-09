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
from typing import Literal
from uuid import UUID, uuid4

from fastmcp.client import Client
from fastmcp.exceptions import ToolError
from pydantic import Field, model_validator

from adgn.agent.agent import Agent
from adgn.agent.bootstrap import TypedBootstrapBuilder, docker_exec_call, read_resource_call
from adgn.agent.handler import SequenceHandler
from adgn.agent.loop_control import InjectItems, RequireAnyTool
from adgn.mcp._shared.constants import PROMPT_EVAL_SERVER_NAME, PROMPT_OPTIMIZATION_RUN_ID_URI, WORKING_DIR
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.compositor.setup import mount_standard_inproc_servers
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.openai_utils.client_factory import build_client
from adgn.openai_utils.model import FunctionCallItem, OpenAIModelProto, SystemMessage, UserMessage
from adgn.openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel
from adgn.openai_utils.types import ReasoningSummary
from adgn.props.agent_setup import build_props_handlers
from adgn.props.cli.common_options import DEFAULT_MAX_LINES
from adgn.props.critic.critic import resolve_critic_scope, run_critic as execute_critic_run
from adgn.props.critic.models import CriticInput
from adgn.props.db import get_session, query_builders as qb
from adgn.props.db.config import get_production_config
from adgn.props.db.models import PromptOptimizationRun, Snapshot
from adgn.props.db.prompts import hash_and_upsert_prompt
from adgn.props.db.sync import get_specimens_base_path, sync_issues_to_db, sync_snapshots_to_db
from adgn.props.docker_env import properties_docker_spec
from adgn.props.grader.grader import grade_critique_by_id
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import AllFilesScope, CriticScopeSpec, ExplicitFileScope
from adgn.props.prompt_optimize.budget_handler import BudgetEnforcementHandler
from adgn.props.prompts.util import render_prompt_template
from adgn.props.prop_utils import specimens_definitions_root
from adgn.props.runs_context import RunsContext, format_timestamp_session
from adgn.props.splits import Split

logger = logging.getLogger(__name__)


# ============================================================================
# Bootstrap Helper
# ============================================================================


def make_po_bootstrap_calls(builder: TypedBootstrapBuilder, runtime_server: str) -> list[FunctionCallItem]:
    """Build bootstrap calls for prompt optimizer: reads PO run ID and critic template.

    Args:
        builder: Bootstrap builder for generating typed tool calls
        runtime_server: Name of the runtime server (for docker exec calls)
    """
    return [
        read_resource_call(builder, server=PROMPT_EVAL_SERVER_NAME, uri=PROMPT_OPTIMIZATION_RUN_ID_URI, max_bytes=256),
        # Read critic template structure from container to show prompt optimizer how its prompts will be used
        docker_exec_call(
            builder,
            server=runtime_server,
            cmd=[
                "python",
                "-c",
                "import adgn.props.critic; import pathlib; p = pathlib.Path(adgn.props.critic.__file__).parent / 'prompts' / 'critic_system.j2.md'; print(p.read_text())",
            ],
        ),
    ]


# ============================================================================
# MCP Server for Prompt Evaluation
# ============================================================================


# --- MCP Tool Input Types ---


class RunCriticToolInput(OpenAIStrictModeBaseModel):
    """MCP tool input for run_critic.

    scope_kind determines which files to review:
    - "all": Review all files that have ground truth issues (scope_paths must be None)
    - "specific": Review only the paths listed in scope_paths (scope_paths required).
      MUST exactly match a pre-defined scope from critic_scopes table.

    Query available scopes:
      SELECT snapshot_slug, files FROM critic_scopes cs
      JOIN snapshots s ON cs.snapshot_slug = s.slug
      WHERE s.split = 'train' ORDER BY snapshot_slug;

    OpenAI strict mode compatible: Flattened discriminated union into optional fields.
    """

    snapshot_slug: SnapshotSlug = Field(description="Snapshot slug (e.g., ducktape/2025-11-26-00)")
    scope_kind: Literal["all", "specific"] = Field(description="Which files to review: 'all' or 'specific'")
    scope_paths: list[str] | None = Field(
        description=(
            "File paths to review (required when scope_kind='specific', must be None when 'all'). "
            "MUST exactly match a scope from critic_scopes table (order-independent)."
        )
    )
    prompt_sha256: str = Field(description="SHA256 hash of the system prompt (from upsert_prompt)")

    @model_validator(mode="after")
    def validate_scope_paths_consistency(self) -> RunCriticToolInput:
        """Ensure scope_paths is set correctly based on scope_kind."""
        if self.scope_kind == "all" and self.scope_paths is not None:
            raise ValueError("scope_paths must be None when scope_kind='all'")
        if self.scope_kind == "specific" and not self.scope_paths:
            raise ValueError("scope_paths is required when scope_kind='specific'")
        return self

    def to_critic_input(self) -> CriticInput:
        """Convert to internal CriticInput format."""
        scope: CriticScopeSpec
        if self.scope_kind == "all":
            scope = AllFilesScope()
        elif self.scope_kind == "specific":
            assert self.scope_paths is not None  # Validated by model_validator
            scope = ExplicitFileScope(files=self.scope_paths)
        else:
            raise ValueError(f"Invalid scope_kind: {self.scope_kind}")
        return CriticInput(snapshot_slug=self.snapshot_slug, files=scope, prompt_sha256=self.prompt_sha256)


class UpsertPromptInput(OpenAIStrictModeBaseModel):
    """Input for upsert_prompt tool."""

    file_path: str = Field(description="Path to prompt file in container filesystem (e.g., /workspace/prompt-v1.txt)")


class UpsertPromptOutput(OpenAIStrictModeBaseModel):
    """Output for upsert_prompt tool."""

    prompt_sha256: str = Field(description="SHA256 hash of prompt content (use this in run_critic)")


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


class RunGraderOutput(OpenAIStrictModeBaseModel):
    """Output for run_grader tool - DB ID and measured recall."""

    grader_run_id: UUID = Field(description="grader_runs.id - Query grader_runs table for full output.grade.")
    recall: float = Field(description="Measured recall for this critique (0.0-1.0)")
    # cumulative_cost_usd: float = Field(
    #     description="Total cumulative cost (USD) for all critic/grader runs in this optimization session so far."
    # )


async def build_server(
    *,
    critic_client: OpenAIModelProto,
    grader_client: OpenAIModelProto,
    hydrator: SnapshotHydrator,
    name: str = "prompt_eval",
    prompt_optimization_run_id: UUID,
    workspace_root: Path,
    budget_limit: float,
    verbose: bool = False,
) -> EnhancedFastMCP:
    """Build prompt_eval server with minimal critic/grader execution tools.

    Provides MCP tools for triggering critic and grader runs:
    - upsert_prompt(file_path) -> prompt_sha256
    - run_critic_all_files(snapshot_slug, prompt_sha256) -> critic_run_id, critique_id
    - run_critic_specific_files(snapshot_slug, paths, prompt_sha256) -> critic_run_id, critique_id
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

    Args:
        critic_client: OpenAI client for running critic evaluations
        grader_client: OpenAI client for running grader evaluations
        hydrator: Snapshot hydrator for source code extraction
        name: MCP server name
        prompt_optimization_run_id: Optional ID of the optimization run for tracking prompts
        workspace_root: Working directory for reading prompt files
        verbose: Verbose output flag

    Returns:
        MCP server with upsert_prompt, run_critic and run_grader tools
    """
    # Ensure snapshots and issues tables are synced on server startup
    base_path = get_specimens_base_path()
    with get_session() as session:
        sync_snapshots_to_db(session, base_path)
        sync_issues_to_db(session, base_path)

    mcp = EnhancedFastMCP(
        name,
        instructions=(
            "Prompt optimization tools: save prompts to database (upsert_prompt), "
            "run critic agents on training examples (run_critic), "
            "grade critiques against ground truth (run_grader). "
            "Query the database for results, costs, and metrics."
        ),
    )

    @mcp.resource(PROMPT_OPTIMIZATION_RUN_ID_URI)
    async def get_prompt_optimization_run_id() -> str:
        """Get the prompt optimization run ID for this session.

        Use this UUID to query costs via sql_po_run_costs (replace <po_run_id> placeholder).
        """
        return str(prompt_optimization_run_id)

    def query_cumulative_cost() -> float:
        """Query cumulative cost for this optimization session.

        Returns:
            Total cumulative cost in USD for all critic/grader runs so far.
        """
        with get_session() as session:
            query = qb.po_run_costs(prompt_optimization_run_id)
            result = session.execute(query).fetchall()
            total: float = sum(row.cost_usd for row in result if row.cost_usd is not None)
            return total

    @mcp.flat_model()
    async def upsert_prompt(payload: UpsertPromptInput) -> UpsertPromptOutput:
        """Save a prompt into the Postgres database. When you want to test or eval a prompt, first make sure it's in the db.

        Workflow:
        1. Write prompt to file using docker_exec (e.g., cat > /workspace/prompt-v1.txt << 'EOF')
        2. Call this tool with the container file path (e.g., /workspace/prompt-v1.txt)
        3. Tool reads from mapped host path, hashes the content, and stores in database
        4. Use returned SHA256 in run_critic calls

        Returns SHA256 hash for use in run_critic tool.
        """
        # Map container path to host path
        # Container paths like /workspace/prompt-v1.txt map to workspace_root/prompt-v1.txt
        container_path = Path(payload.file_path)
        working_dir_str = str(WORKING_DIR) + "/"
        if not str(container_path).startswith(working_dir_str):
            raise ValueError(f"File path must be in {WORKING_DIR}/ directory, got: {payload.file_path}")

        relative_path = str(container_path).removeprefix(working_dir_str)
        host_path = workspace_root / relative_path

        if not host_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {host_path}")

        # Read prompt text from host filesystem
        prompt_text = host_path.read_text(encoding="utf-8")

        # Hash and upsert to database (with optional run ID for tracking)
        prompt_sha256 = hash_and_upsert_prompt(prompt_text, prompt_optimization_run_id)

        return UpsertPromptOutput(prompt_sha256=prompt_sha256)

    @mcp.flat_model()
    async def run_critic(payload: RunCriticToolInput) -> RunCriticOutput:
        """Runs a critic agent on a snapshot to find code quality issues.

        Scope modes:
        - scope_kind="all": Review ALL files with ground truth issues (full snapshot review)
          - REQUIRED for validation split
          - More realistic evaluation (comprehensive codebase review)
        - scope_kind="specific": Review only specified files (TRAIN split only)
          - Files MUST EXACTLY MATCH a pre-defined scope from critic_scopes table
          - Arbitrary file selections will be rejected
          - Faster iteration for debugging specific failure patterns

        IMPORTANT: When using scope_kind="specific", the scope_paths must match a known scope exactly.
        Query available scopes with:
          SELECT snapshot_slug, files FROM critic_scopes cs
          JOIN snapshots s ON cs.snapshot_slug = s.slug
          WHERE s.split = 'train' ORDER BY snapshot_slug;

        The critic uses your specified prompt (via prompt_sha256) to analyze code and report issues.
        Returns database IDs - query the database for results, costs, and execution traces.

        Parameters:
        - snapshot_slug: Which snapshot to review (e.g., "ducktape/2025-11-20-00")
        - scope_kind: "all" or "specific"
        - scope_paths: List of file paths (required when scope_kind="specific", must be None when "all").
          Must exactly match a scope from critic_scopes table (order-independent).
        - prompt_sha256: Which prompt to use (from upsert_prompt)

        Returns:
        - critic_run_id: Query critic_runs table for full output (issues, costs, model)
        - critique_id: Use with run_grader to evaluate against ground truth

        Train/Valid Split Access (Anti-Cheating Design):
        - TRAIN: Full access granted. Run on any scope. Query all details: critic_runs, critiques,
          true_positives, false_positives tables. Use for debugging/iteration.

        - VALID: Restricted access to prevent overfitting:
          - Must use scope_kind="all" (full snapshot only)
          - Individual run details HIDDEN by database Row-Level Security (RLS)
          - Query validation results ONLY via valid_full_snapshot_grader_metrics view (aggregate metrics)

        This ensures validation recall is a trustworthy proxy for test performance.
        """
        critic_input = payload.to_critic_input()

        # Check snapshot exists and enforce validation restrictions
        # Extract known_scopes while session is open (avoid lazy loading after session closes)
        known_scopes: list[frozenset[str]] = []
        with get_session() as session:
            db_snapshot = session.query(Snapshot).filter_by(slug=critic_input.snapshot_slug).first()
            if db_snapshot is None:
                raise ValueError(f"Snapshot '{critic_input.snapshot_slug}' not found in database")

            # Validation split: must use scope_kind="all" (full snapshot)
            if db_snapshot.split == "valid" and payload.scope_kind == "specific":
                raise ValueError(
                    f"Validation split snapshot '{critic_input.snapshot_slug}' must use scope_kind='all' "
                    f"(full snapshot evaluation only). Cannot run on subset of files."
                )

            # Extract known scopes from db_snapshot while session is still open
            if payload.scope_kind == "specific":
                for scope in db_snapshot.critic_scopes:
                    known_scopes.append(frozenset(scope.files))

        # Resolve files for prompt rendering
        resolved_files = await resolve_critic_scope(snapshot_slug=critic_input.snapshot_slug, files=critic_input.files)

        # Load and hydrate specimen for content_root
        async with hydrator.hydrate(critic_input.snapshot_slug) as hydrated:
            # Validate explicit files match a known scope (only for scope_kind="specific")
            if payload.scope_kind == "specific":
                # Validate that file list matches a known scope (order-independent)
                requested_files_set = frozenset(str(f) for f in resolved_files)

                if requested_files_set not in known_scopes:
                    raise ValueError(
                        f"Files do not match any known scope for '{critic_input.snapshot_slug}'. "
                        f"Requested: {sorted(requested_files_set)}. "
                        f"Query available scopes: SELECT snapshot_slug, files FROM critic_scopes cs "
                        f"JOIN snapshots s ON cs.snapshot_slug = s.slug WHERE s.split = 'train';"
                    )

            # Execute critic run
            _critic_success, critic_run_id, critique_id = await execute_critic_run(
                input_data=critic_input,
                client=critic_client,
                content_root=hydrated.content_root,
                prompt_optimization_run_id=prompt_optimization_run_id,
                mount_properties=False,
                extra_handlers=(),
                verbose=verbose,
            )

            if critique_id is None:
                raise RuntimeError("Critic run completed but no critique was created")

            return RunCriticOutput(critic_run_id=critic_run_id, critique_id=critique_id)

    @mcp.flat_model()
    async def run_grader(payload: RunGraderInput) -> RunGraderOutput:
        """Given a critique produced by a critic, runs a grader agent to grade the critique against ground truth labels.

        Compares what the critic reported against what should have been found (ground truth).
        Computes recall and detailed coverage information.

        Parameters:
        - critique_id: The critique to grade (from run_critic's return value)

        Returns:
        - grader_run_id: Query grader_runs table for results

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
          ONLY aggregate metrics visible via valid_full_snapshot_grader_metrics view.
          Example: SELECT snapshot_slug, recall FROM valid_full_snapshot_grader_metrics;

        This ensures validation recall is a trustworthy proxy for test performance. You cannot inspect
        validation details to reverse-engineer answers.

        Use validation aggregates to measure generalization performance across all validation specimens.
        """
        # Execute GraderRun by critique_id (fetches critique from DB, saves grader run to DB)
        with get_session() as session:
            grader_run_id = await grade_critique_by_id(
                session=session,
                critique_id=payload.critique_id,
                client=grader_client,
                prompt_optimization_run_id=prompt_optimization_run_id,
                verbose=verbose,
            )

            # Query recall from the grader run output
            from adgn.props.db.models import GraderRun as DBGraderRun

            grader_run = session.get(DBGraderRun, grader_run_id)
            if not grader_run:
                raise ToolError(f"Grader run {grader_run_id} not found in database")
            if not grader_run.output:
                raise ToolError(f"Grader run {grader_run_id} has no output")

            recall = grader_run.output.recall

        return RunGraderOutput(grader_run_id=grader_run_id, recall=recall)

    return mcp


# ============================================================================
# Prompt Optimizer
# ============================================================================


async def run_prompt_optimizer(
    budget: float,
    ctx: RunsContext,
    hydrator: SnapshotHydrator,
    optimizer_model: str,
    critic_model: str,
    grader_model: str,
    out_dir: Path | None = None,
    verbose: bool = False,
    max_lines: int = DEFAULT_MAX_LINES,
) -> None:
    """Run a Prompt Engineering agent to optimize a critic system prompt.

    Args:
        budget: Dollar budget for optimization
        ctx: Runs context for path derivation
        hydrator: Snapshot hydrator for source code extraction
        out_dir: Optional output directory
        optimizer_model: Model to use for prompt optimizer agent
        critic_model: Model to use for critic evaluations
        grader_model: Model to use for grader evaluations
        verbose: Verbose output flag

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

        # Build extra volumes for Docker (snapshots + definitions)
        # Format: {host_path: {"bind": container_path, "mode": "ro"|"rw"}}
        # Train snapshots source code (ro) - mount each separately
        extra_volumes = {
            str(path.resolve()): {"bind": f"/snapshots/train/{slug}", "mode": "ro"}
            for slug, path in snapshot_paths.items()
        }

        # Ground truth issues (TPs/FPs) are now accessed via database
        # No longer mount libsonnet definitions from filesystem

        # Get database config (fails fast if env vars not set)
        config = get_production_config()
        agent_conn = config.agent_for_container  # Container-to-container access
        logger.info(f"Agent database: host={agent_conn.host}, db={agent_conn.database}, user={agent_conn.user}")

        # Create Docker wiring (no /repo mount - would leak test specimen definitions!)
        # workspace_root will be mounted as /workspace (rw mode for agent to write prompts)
        wiring = properties_docker_spec(
            workspace_root=session_dir,
            mount_properties=False,  # No property definitions mounted
            extra_volumes=extra_volumes,
            ephemeral=False,  # Use persistent container to maintain environment
            workspace_mode="rw",  # Agent needs to write prompt iterations
            db_conn=agent_conn,  # Agent-restricted database access (critical for PO agent)
            network_mode="props_default",  # Join postgres network for database access
        )

        # Create PromptOptimizationRun record for tracking

        # Generate transcript ID for database event tracking
        transcript_id = uuid4()
        logger.info(f"Prompt optimizer transcript_id: {transcript_id}")

        with get_session() as session:
            po_run = PromptOptimizationRun(
                transcript_id=transcript_id,
                budget_limit=budget,
                config={
                    "optimizer_model": optimizer_model,
                    "critic_model": critic_model,
                    "grader_model": grader_model,
                    "session_dir": str(session_dir),
                },
            )
            session.add(po_run)
            session.flush()
            prompt_optimization_run_id = po_run.id
            session.commit()

        logger.info(f"Created PromptOptimizationRun: {prompt_optimization_run_id}")

        # Use Compositor as async context manager to ensure cleanup
        async with Compositor() as comp:
            runtime_server = await wiring.attach(comp)  # Attaches runtime MCP server

            # TODO: Auto-infer prompt_optimization_run_id in MCP server tools instead of manually passing it here
            # The prompt eval server (and grader/critic tools) should be able to auto-detect when they're
            # being called within a PO session context (e.g., via environment variable, session metadata,
            # or resource lookup) rather than requiring manual ID propagation through all tool calls.
            # This would eliminate the need to manually set prompt_optimization_run_id in RunCriticInput
            # and RunGraderInput.

            # Create and mount prompt_eval server, keeping reference for introspection
            prompt_eval_server = await build_server(
                critic_client=build_client(critic_model),
                grader_client=build_client(grader_model),
                hydrator=hydrator,
                name=PROMPT_EVAL_SERVER_NAME,
                prompt_optimization_run_id=prompt_optimization_run_id,
                workspace_root=session_dir,
                budget_limit=budget,
                verbose=verbose,
            )
            await comp.mount_inproc(PROMPT_EVAL_SERVER_NAME, prompt_eval_server)

            # Collect servers for tool schema extraction
            servers = {wiring.server_name: runtime_server}

            user = f"""Your budget is: ${budget:.2f}.

Models in use:
- Optimizer (you): {optimizer_model}
- Critic: {critic_model}
- Grader: {grader_model}

Note: The database may contain results from other models. These historical results might provide useful insights for optimization.

Iterate to find an optimal prompt for a code reviewer/critic LLM agent.
Prioritize recall first, then precision.
"""

            # Use the prompt_eval server reference for introspection
            builder = TypedBootstrapBuilder.for_server(prompt_eval_server)
            bootstrap_calls = make_po_bootstrap_calls(builder, runtime_server=wiring.server_name)
            bootstrap = SequenceHandler([InjectItems(items=bootstrap_calls)])

            handlers: list = [
                bootstrap,
                *build_props_handlers(
                    transcript_id=transcript_id,
                    verbose_prefix=f"[OPTIMIZER:{str(transcript_id)[:8]}] " if verbose else None,
                    servers=servers,
                    max_lines=max_lines,
                ),
            ]
            async with Client(comp) as mcp_client:
                await mount_standard_inproc_servers(compositor=comp)
                agent = await Agent.create(
                    mcp_client=mcp_client,
                    client=build_client(optimizer_model),
                    handlers=handlers,
                    parallel_tool_calls=True,
                    reasoning_summary=ReasoningSummary.detailed,
                    tool_policy=RequireAnyTool(),
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

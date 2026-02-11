"""Prompt optimizer implementation.

Runs an LLM agent to optimize critic prompts using train/valid/test splits
with budget tracking and granular evaluation tools.

Includes MCP server for prompt evaluation (run_critic/run_grader tools).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from uuid import UUID, uuid4

from fastmcp.client import Client
from pydantic import BaseModel, ConfigDict, Field

from adgn.agent.agent import MiniCodex
from adgn.agent.bootstrap import TypedBootstrapBuilder, read_resource_call
from adgn.agent.handler import SequenceHandler
from adgn.agent.loop_control import InjectItems, RequireAnyTool
from adgn.mcp._shared.constants import PROMPT_EVAL_SERVER_NAME, WORKING_DIR
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.compositor.setup import mount_standard_inproc_servers
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.openai_utils.client_factory import build_client
from adgn.openai_utils.model import FunctionCallItem, OpenAIModelProto
from adgn.openai_utils.types import ReasoningSummary
from adgn.props.agent_setup import build_props_handlers
from adgn.props.critic.critic import resolve_critic_scope, run_critic as execute_critic_run
from adgn.props.critic.models import ALL_FILES_WITH_ISSUES, CriticInput
from adgn.props.db import get_session, query_builders as qb
from adgn.props.db.models import PromptOptimizationRun, Snapshot
from adgn.props.db.prompts import hash_and_upsert_prompt
from adgn.props.db.sync import sync_issues_to_db, sync_snapshots_to_db
from adgn.props.docker_env import properties_docker_spec
from adgn.props.grader.grader import grade_critique_by_id
from adgn.props.prompts.util import render_prompt_template
from adgn.props.runs_context import RunsContext, format_timestamp_session
from adgn.props.snapshot_registry import SnapshotRegistry

logger = logging.getLogger(__name__)


# NOTE: BudgetHandler removed pending refactor - PromptEvalState no longer exists
# Budget tracking needs to be reimplemented with the new prompt_eval server API


# ============================================================================
# Bootstrap Helper
# ============================================================================


def make_po_bootstrap_calls(builder: TypedBootstrapBuilder) -> list[FunctionCallItem]:
    """Build bootstrap calls for prompt optimizer: reads PO run ID."""
    return [
        read_resource_call(
            builder, server=PROMPT_EVAL_SERVER_NAME, uri="resource://prompt_eval/po_run_id", max_bytes=256
        )
    ]


# ============================================================================
# MCP Server for Prompt Evaluation
# ============================================================================


class UpsertPromptInput(BaseModel):
    """Input for upsert_prompt tool."""

    file_path: str = Field(
        description="Path to prompt file in container filesystem (e.g., /workspace/prompt-v1.txt). Use docker_exec write_file first to create it."
    )

    model_config = ConfigDict(extra="forbid")


class UpsertPromptOutput(BaseModel):
    """Output for upsert_prompt tool."""

    prompt_sha256: str = Field(description="SHA256 hash of prompt content (use this in run_critic)")

    model_config = ConfigDict(extra="forbid")


class RunCriticOutput(BaseModel):
    """Output for run_critic tool - DB IDs for critic run and generated critique."""

    critic_run_id: UUID = Field(description="Database ID of critic run. Query DB for results/metrics/costs.")
    critique_id: UUID = Field(description="UUID of critique (linked to critic run). Use for run_grader.")

    model_config = ConfigDict(extra="forbid")


class RunGraderInput(BaseModel):
    """Input for run_grader tool.

    Note: model is NOT included - the server is bound to a specific client/model at build time.
    """

    critique_id: UUID = Field(description="UUID of critique to grade (from critiques table)")

    model_config = ConfigDict(extra="forbid")


class RunGraderOutput(BaseModel):
    """Output for run_grader tool - only the DB ID."""

    grader_run_id: UUID = Field(description="Database ID of grader run. Query DB for results/metrics/costs.")

    model_config = ConfigDict(extra="forbid")


async def build_server(
    *,
    client: OpenAIModelProto,
    registry: SnapshotRegistry,
    name: str = "prompt_eval",
    prompt_optimization_run_id: UUID,
    workspace_root: Path,
    verbose: bool = False,
) -> NotifyingFastMCP:
    """Build prompt_eval server with minimal critic/grader execution tools.

    Provides MCP tools for triggering critic and grader runs:
    - upsert_prompt(file_path) -> prompt_sha256
    - run_critic(specimen, scope, prompt_sha256) -> critic_run_id, critique_id
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

    Args:
        client: OpenAI client for running evaluations
        registry: Snapshot registry (required, no default)
        name: MCP server name
        prompt_optimization_run_id: Optional ID of the optimization run for tracking prompts
        workspace_root: Working directory for reading prompt files
        verbose: Verbose output flag

    Returns:
        MCP server with upsert_prompt, run_critic and run_grader tools
    """
    # Ensure snapshots and issues tables are synced on server startup
    with get_session() as session:
        sync_snapshots_to_db(session, registry=registry)
        sync_issues_to_db(session, registry=registry)

    mcp = NotifyingFastMCP(
        name, instructions="Prompt Evaluation server — manage prompts, trigger critic/grader runs, query DB for results"
    )

    @mcp.resource("resource://prompt_eval/po_run_id")
    async def get_po_run_id() -> UUID:
        """Get the prompt optimization run ID for this session.

        Use this UUID to query costs via sql_po_run_costs (replace <po_run_id> placeholder).
        """
        return prompt_optimization_run_id

    @mcp.tool(flat=True)
    async def upsert_prompt(payload: UpsertPromptInput) -> UpsertPromptOutput:
        """Hash prompt text and upsert to database.

        Workflow:
        1. Write prompt to file using docker_exec write_file
        2. Call this tool with the container file path
        3. Tool reads from mapped host path and hashes
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

    @mcp.tool(flat=True)
    async def run_critic(payload: CriticInput) -> RunCriticOutput:
        """Execute critic agent on specimen to generate critique (list of reported issues).

        Runs the critic agent on specified files within a specimen using the provided prompt.
        The critic agent analyzes code and reports issues it finds.

        Returns database IDs for the run - query the database to access:
        - critic_runs.output (full CriticOutput with reported issues, costs, model info)
        - critiques.payload (structured issue list from agent)
        - events (full execution trace by transcript_id)

        Files parameter:
        - Set of Path objects: scope to specific files (train specimens only)
        - "all": evaluate all files with known ground-truth issues (required for validation split)

        Validation split restriction: must use files="all" (full specimen evaluation only).

        Cost tracking (TODO): costs embedded in output JSONB but not enforced at tool level yet.
        """
        # Check snapshot split and enforce validation restriction
        with get_session() as session:
            db_snapshot = session.query(Snapshot).filter_by(slug=payload.snapshot_slug).first()
            if db_snapshot is None:
                raise ValueError(f"Snapshot '{payload.snapshot_slug}' not found in database")

            # Validation split: must use files=ALL_FILES_WITH_ISSUES
            if db_snapshot.split == "valid" and payload.files != ALL_FILES_WITH_ISSUES:
                raise ValueError(
                    f"Validation split snapshot '{payload.snapshot_slug}' must use files=\"{ALL_FILES_WITH_ISSUES}\" (full specimen evaluation only). "
                    f"Cannot run on subset of files."
                )

        # Resolve files for prompt rendering and validation
        resolved_files = await resolve_critic_scope(
            snapshot_slug=payload.snapshot_slug, files=payload.files, registry=registry
        )

        # Load and hydrate specimen for content_root
        async with registry.load_and_hydrate(payload.snapshot_slug) as hydrated:
            # Validate explicit files exist (when not using sentinel)
            if payload.files != ALL_FILES_WITH_ISSUES:
                specimen_files = set(hydrated.all_discovered_files.keys())
                if invalid_files := resolved_files - specimen_files:
                    raise ValueError(
                        f"Invalid files for specimen '{payload.snapshot_slug}': {sorted(str(f) for f in invalid_files)}. "
                        f"Available files: {sorted(str(f) for f in specimen_files)[:10]}..."
                    )

            # Execute critic run (saves to DB automatically; fetches system prompt from DB internally
            # and builds user prompt from resolved files)
            _critic_success, critic_run_id, critique_id = await execute_critic_run(
                input_data=payload,
                client=client,
                content_root=hydrated.content_root,
                registry=registry,
                mount_properties=False,
                extra_handlers=(),
                verbose=verbose,
            )

            if critique_id is None:
                raise RuntimeError("Critic run completed but no critique was created")
            return RunCriticOutput(critic_run_id=critic_run_id, critique_id=critique_id)

    @mcp.tool(flat=True)
    async def run_grader(payload: RunGraderInput) -> RunGraderOutput:
        """Execute grader agent to evaluate a critique against ground truth.

        Runs the grader agent to compare a critic's reported issues against ground truth.
        Computes precision, recall, true positives, false positives, false negatives.

        Returns database ID for the run - query the database to access:
        - grader_runs.output (full GraderOutput with grade.recall, grade.precision, grade.metrics)
        - grader_runs.critique_id (links back to the critique that was graded)
        - Join to critic_runs via critique_id to get prompt_sha256, model, files scoped
        - Join to specimens to check split (train has per-specimen access, valid only via aggregate view)
        - events (full execution trace by transcript_id)

        Grade metrics in output JSONB:
        - grade.recall: fraction of ground-truth issues found (PRIMARY METRIC)
        - grade.precision: fraction of reported issues that match ground truth (may be low due to sparse labeling)
        - grade.metrics: {true_positives, false_positives, false_negatives} counts

        Cost tracking (TODO): costs embedded in output JSONB but not enforced at tool level yet.
        """
        # Execute GraderRun by critique_id (fetches critique from DB, saves grader run to DB)
        with get_session() as session:
            grader_run_id = await grade_critique_by_id(
                session=session, critique_id=payload.critique_id, client=client, registry=registry, verbose=verbose
            )

        return RunGraderOutput(grader_run_id=grader_run_id)

    return mcp


# ============================================================================
# Prompt Optimizer
# ============================================================================


async def run_prompt_optimizer(
    budget: float,
    ctx: RunsContext,
    registry: SnapshotRegistry,
    out_dir: Path | None = None,
    model: str = "gpt-5",
    verbose: bool = False,
) -> None:
    """Run a Prompt Engineering agent to optimize a critic system prompt.

    Args:
        budget: Dollar budget for optimization
        ctx: Runs context for path derivation
        registry: Snapshot registry (required, no default - caller must provide)
        out_dir: Optional output directory
        model: Model to use (default gpt-5)
        verbose: Verbose output flag

    Hydrates train specimens and mounts them with definitions via Docker.
    The agent can query train data and valid aggregates via database if PROPS_AGENT_DB_URL is set.
    """
    # Render system prompt with compiled SQL queries from builders
    system = render_prompt_template(
        "prompt_optimizer_system.j2.md",
        sql_list_train=qb.compile_to_sql(qb.list_train_snapshots()),
        sql_list_train_tps=qb.compile_to_sql(qb.list_train_true_positives()),
        sql_list_train_fps=qb.compile_to_sql(qb.list_train_false_positives()),
        sql_count_issues_by_snapshot=qb.compile_to_sql(qb.count_issues_by_snapshot(split="train")),
        sql_recent_graders=qb.compile_to_sql(qb.recent_grader_results(limit=10)),
        sql_valid_agg_view=qb.compile_to_sql(qb.valid_aggregates_view()),
        # Parameterized queries - compile with placeholders for agent to fill in
        sql_critique_for_specimen=qb.compile_to_sql_with_placeholders(qb.critiques_for_snapshot_parameterized()),
        sql_link_to_prompt=qb.compile_to_sql_with_placeholders(qb.link_grader_to_prompt_parameterized()),
        sql_tools_used=qb.compile_to_sql_with_placeholders(qb.tools_used_by_transcript_parameterized()),
        sql_tool_sequence=qb.compile_to_sql_with_placeholders(qb.tool_sequence_by_transcript_parameterized()),
        sql_failed_tools=qb.compile_to_sql_with_placeholders(qb.failed_tools_by_transcript_parameterized()),
        sql_blocked_valid_critiques=qb.compile_to_sql(qb.blocked_valid_critiques()),
        sql_blocked_valid_grader_runs=qb.compile_to_sql(qb.blocked_valid_grader_runs()),
        sql_blocked_valid_events=qb.compile_to_sql(qb.blocked_valid_events()),
        sql_po_run_costs=qb.compile_to_sql_with_placeholders(qb.po_run_costs_parameterized()),
    )

    # Session directory (inline adhoc_run_dir - only called here)
    ts = format_timestamp_session()
    if out_dir is not None:
        session_dir = out_dir.resolve()
    else:
        session_dir = ctx.base_dir / "prompt_optimize" / f"session_{ts}"
        session_dir.mkdir(parents=True, exist_ok=True)
        session_dir = session_dir.resolve()

    # Hydrate train specimens and keep alive for Docker mounting
    async with registry.hydrate_train_specimens() as (train_specimens, _defs_root):
        # Build extra volumes for Docker (specimens + definitions)
        # Format: {host_path: {"bind": container_path, "mode": "ro"|"rw"}}
        extra_volumes = {}

        # Train snapshots source code (ro) - mount each separately
        for slug, path in train_specimens.items():
            extra_volumes[str(path.resolve())] = {"bind": f"/snapshots/train/{slug}", "mode": "ro"}

        # Ground truth issues (TPs/FPs) are now accessed via database
        # No longer mount libsonnet definitions from filesystem

        # Get agent_user database URL from environment
        agent_db_url = os.environ.get("PROPS_AGENT_DB_URL")
        logger.info(f"PROPS_AGENT_DB_URL from environment: {agent_db_url}")
        if not agent_db_url:
            logger.warning(
                "PROPS_AGENT_DB_URL not set - agent will not have database access. "
                "Set to enable querying train data and valid aggregates."
            )
        else:
            # Transform localhost:5433 → props-postgres:5432 for Docker network access
            agent_db_url = agent_db_url.replace("localhost:5433", "props-postgres:5432")
            logger.info(f"Transformed agent_db_url for container: {agent_db_url}")

        # Create Docker wiring (no /repo mount - would leak test specimen definitions!)
        # workspace_root will be mounted as /workspace (rw mode for agent to write prompts)
        wiring = properties_docker_spec(
            workspace_root=session_dir,
            mount_properties=False,  # No property definitions mounted
            extra_volumes=extra_volumes,
            ephemeral=False,  # Use persistent container to maintain environment
            workspace_mode="rw",  # Agent needs to write prompt iterations
            db_url=agent_db_url,  # Agent-restricted database access
            network_mode=("props_default" if agent_db_url else None),  # Join postgres network if DB enabled
        )

        # Create PromptOptimizationRun record for tracking

        with get_session() as session:
            po_run = PromptOptimizationRun(
                budget_limit=budget, config={"model": model, "session_dir": str(session_dir)}
            )
            session.add(po_run)
            session.flush()
            prompt_optimization_run_id = po_run.id
            session.commit()

        logger.info(f"Created PromptOptimizationRun: {prompt_optimization_run_id}")

        comp = Compositor("compositor")
        runtime_server = await wiring.attach(comp)  # Attaches runtime MCP server

        # Create and mount prompt_eval server, keeping reference for introspection
        prompt_eval_server = await build_server(
            client=build_client(model),
            registry=registry,
            name=PROMPT_EVAL_SERVER_NAME,
            prompt_optimization_run_id=prompt_optimization_run_id,
            workspace_root=session_dir,
            verbose=verbose,
        )
        await comp.mount_inproc(PROMPT_EVAL_SERVER_NAME, prompt_eval_server)

        # Collect servers for tool schema extraction
        servers = {wiring.server_name: runtime_server}

        user = f"""Your budget is: ${budget:.2f}.

Iterate to find an optimal prompt for a code reviewer/critic LLM agent.
Prioritize recall first, then precision.
"""

        # Generate transcript ID for database event tracking
        transcript_id = uuid4()
        logger.info(f"Prompt optimizer transcript_id: {transcript_id}")

        # Use the prompt_eval server reference for introspection
        builder = TypedBootstrapBuilder.for_server(prompt_eval_server)
        bootstrap_calls = make_po_bootstrap_calls(builder)
        bootstrap = SequenceHandler([InjectItems(items=bootstrap_calls)])

        handlers: list = [
            bootstrap,
            *build_props_handlers(
                transcript_id=transcript_id, verbose_prefix="[OPTIMIZER] " if verbose else None, servers=servers
            ),
        ]
        async with Client(comp) as mcp_client:
            await mount_standard_inproc_servers(compositor=comp)
            agent = await MiniCodex.create(
                mcp_client=mcp_client,
                system=system,
                client=build_client(model),
                handlers=handlers,
                parallel_tool_calls=True,
                reasoning_summary=ReasoningSummary.detailed,
                tool_policy=RequireAnyTool(),
            )

            await agent.run(user)

        logger.info(f"Optimization session complete. Results in: {session_dir}")
        # NOTE: Cost tracking removed pending refactor - pe_state no longer available
        logger.info(f"Budget: ${budget:.2f}")

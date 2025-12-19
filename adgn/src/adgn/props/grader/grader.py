"""Grader agent execution and environment.

Runs the grader agent to evaluate critic output against ground truth.
Uses MCP-over-HTTP for agent communication.
"""

from collections.abc import Sequence
import logging
from pathlib import Path
from uuid import UUID, uuid4

import aiodocker
from fastmcp.client import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AuthProvider
from sqlalchemy.orm import Session

from adgn.agent.agent import Agent
from adgn.agent.bootstrap import TypedBootstrapBuilder, read_package_files_call
from adgn.agent.handler import AbortIf, BaseHandler, RedirectOnTextMessageHandler, SequenceHandler
from adgn.agent.loop_control import AllowAnyToolOrTextMessage, InjectItems
from adgn.agent.turn_limit import MaxTurnsExceededError, MaxTurnsHandler
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.openai_utils.model import OpenAIModelProto, SystemMessage
from adgn.openai_utils.types import ReasoningSummary
from adgn.props.agent_setup import AgentEnvironment, build_props_handlers
from adgn.props.cli.common_options import DEFAULT_MAX_LINES
from adgn.props.db import get_session
from adgn.props.db.config import DatabaseConfig
from adgn.props.db.models import CanonicalIssuesSnapshot, CriticRun, GraderRun as DBGraderRun, GraderRunStatus, Snapshot
from adgn.props.display import short_uuid
from adgn.props.grader.exceptions import GraderDidNotSubmitError
from adgn.props.grader.models import FalsePositiveID, GraderInput, KnownFalsePositive, TruePositiveID, TruePositiveIssue
from adgn.props.grader.persistence import fp_to_db, tp_to_db
from adgn.props.grader.submit_server import GraderSubmitServer as GraderSubmitServerSQL
from adgn.props.grader.user_manager import GraderUserManager
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import SnapshotSlug
from adgn.props.models.critic_scopes import AllFilesScope, ExplicitFileScope
from adgn.props.models.true_positive import should_catch_occurrence, should_show_fp_occurrence
from adgn.props.prompts.util import render_prompt_template
from adgn.props.rationale import Rationale

logger = logging.getLogger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================


def _tp_from_orm(orm_tp) -> TruePositiveIssue:
    """Convert ORM TruePositive to grader representation (module-private)."""
    return TruePositiveIssue(
        id=TruePositiveID(orm_tp.tp_id), rationale=Rationale(orm_tp.rationale), occurrences=orm_tp.occurrences
    )


def _fp_from_orm(orm_fp) -> KnownFalsePositive:
    """Convert ORM FalsePositive to grader representation (module-private)."""
    return KnownFalsePositive(
        id=FalsePositiveID(orm_fp.fp_id), rationale=Rationale(orm_fp.rationale), occurrences=orm_fp.occurrences
    )


# =============================================================================
# Agent Execution
# =============================================================================


async def _run_grader_agent(
    *,
    hydrator: SnapshotHydrator,
    docker_client: aiodocker.Docker,
    client: OpenAIModelProto,
    transcript_id: UUID,
    input_data: GraderInput,
    verbose: bool,
    extra_handlers: tuple[BaseHandler, ...],
    db_config: DatabaseConfig,
    max_lines: int = DEFAULT_MAX_LINES,
    max_turns: int,
    grader_run_id: UUID,
) -> None:
    """Run the grader agent via MCP-over-HTTP.

    Uses GraderAgentEnvironment which manages:
    - Temporary database user with RLS scoping
    - HTTP MCP server with grader_submit tool
    - Docker container with docker_exec
    - Hydrated snapshot mounted at /snapshots/<slug>/

    Args:
        hydrator: Snapshot hydrator for mounting snapshot source code
        client: OpenAI model client
        transcript_id: Transcript ID for event tracking
        input_data: Grader input with critic_run_id
        verbose: Enable verbose output
        extra_handlers: Additional handlers
        db_config: Database configuration
        max_lines: Max lines for verbose display
        max_turns: Maximum agent turns before failure
        grader_run_id: UUID of the grader run
    """
    # Derive snapshot_slug and snapshot_split from input_data.critic_run_id
    with get_session() as session:
        critic_run = session.get(CriticRun, input_data.critic_run_id)
        if critic_run is None:
            raise ValueError(f"Critic run {input_data.critic_run_id} not found")

        snapshot_slug = critic_run.snapshot_slug
        snapshot = session.get(Snapshot, snapshot_slug)
        if snapshot is None:
            raise ValueError(f"Snapshot {snapshot_slug} not found")
        snapshot_split = snapshot.split

    # Use GraderAgentEnvironment which manages:
    # - Temporary database user with RLS scoping
    # - HTTP MCP server with grader_submit tool
    # - Docker container with docker_exec
    # - Hydrated snapshot mounted at /snapshots/<slug>/
    comp_ctx = GraderAgentEnvironment(
        snapshot_slug=snapshot_slug,
        docker_client=docker_client,
        hydrator=hydrator,
        grader_run_id=grader_run_id,
        critic_run_id=input_data.critic_run_id,
        db_config=db_config,
    )

    async with comp_ctx as handle, Client(handle) as mcp_client:
        # SQL workflow: render grader_system.j2.md template
        system = render_prompt_template("grader/prompts/grader_system.j2.md")

        # Build handlers list, add bootstrap
        handlers_list: list[BaseHandler] = []

        # Bootstrap: read snapshot_slug from grader_submit server resource
        builder = TypedBootstrapBuilder.for_server(handle.runtime.server)

        # Use agent environment's bootstrap method
        logger.info("Grader bootstrap: using agent environment bootstrap items")
        bootstrap_calls = comp_ctx.bootstrap_items(builder, handle.runtime)
        handlers_list.append(SequenceHandler([InjectItems(items=bootstrap_calls)]))

        # Define abort condition: check database status for grader completion
        def _grader_ready_state() -> bool:
            """Check if grader run is completed in database.

            Used by AbortIf handler to stop agent loop when grading is done.
            """
            with get_session() as session:
                found_run = session.get(DBGraderRun, grader_run_id)
                return found_run is not None and found_run.status in (
                    GraderRunStatus.COMPLETED,
                    GraderRunStatus.MAX_TURNS_EXCEEDED,
                    GraderRunStatus.REPORTED_FAILURE,
                )

        handlers_list.extend(
            [
                AbortIf(should_abort=_grader_ready_state),
                *await build_props_handlers(
                    transcript_id=transcript_id,
                    verbose_prefix=(
                        f"[GRADER {short_uuid(transcript_id)} {snapshot_split} {snapshot_slug}] " if verbose else None
                    ),
                    compositor=handle,
                    max_lines=max_lines,
                ),
                RedirectOnTextMessageHandler(
                    reminder_message=(
                        "You are a grader agent. Your grading has not yet been submitted to the MCP server. "
                        "Your task is to evaluate the given input critique by comparing it against canonical findings "
                        "using the provided MCP tools, then submit your grading. "
                        "This is not an interactive workflow - complete your analysis and submit the grading via the MCP tool. "
                        "Do not attempt to submit your grade by sending a text message - use the tool."
                    )
                ),
                *extra_handlers,
                MaxTurnsHandler(max_turns=max_turns),
            ]
        )

        agent = await Agent.create(
            mcp_client=mcp_client,
            client=client,
            handlers=handlers_list,
            dynamic_instructions=handle.render_agent_dynamic_instructions,
            parallel_tool_calls=True,
            reasoning_summary=ReasoningSummary.detailed,
            tool_policy=AllowAnyToolOrTextMessage(),
        )
        agent.insert_messages([SystemMessage.text(system)])
        try:
            await agent.run()

            # Agent completed normally - validate database status
            with get_session() as session:
                found_run = session.get(DBGraderRun, grader_run_id)
                if found_run is None:
                    raise GraderDidNotSubmitError(f"Grader run {grader_run_id} not found in database")
                if found_run.status != GraderRunStatus.COMPLETED:
                    raise GraderDidNotSubmitError(
                        f"Grader run {grader_run_id} completed but status is {found_run.status}, expected COMPLETED"
                    )

            return
        except MaxTurnsExceededError:
            # Agent ran out of turns - mark as max_turns_exceeded in database
            # NOTE: max_turns_exceeded is taken as recall=0.0 (see query_builders.py:803-806)
            logger.warning(
                f"Grader hit max turns limit ({max_turns}) for {snapshot_slug}, "
                f"transcript_id={short_uuid(transcript_id)}"
            )
            with get_session() as session:
                found_run = session.get(DBGraderRun, grader_run_id)
                if found_run:
                    found_run.status = GraderRunStatus.MAX_TURNS_EXCEEDED
                    session.commit()
                return


# =============================================================================
# Grader Run Function
# =============================================================================


async def run_grader(
    *,
    input_data: GraderInput,
    client: OpenAIModelProto,
    hydrator: SnapshotHydrator,
    canonical_tps: list[TruePositiveIssue],
    canonical_fps: list[KnownFalsePositive],
    docker_client: aiodocker.Docker,
    db_config: DatabaseConfig,
    extra_handlers: tuple[BaseHandler, ...] = (),
    verbose: bool = False,
    max_lines: int = DEFAULT_MAX_LINES,
    max_turns: int,
) -> UUID:
    """Run grader agent: evaluate critique against ground truth, persist to DB.

    Uses GraderAgentEnvironment which manages:
    - Temporary database user with RLS scoping
    - HTTP MCP server with grader_submit tool
    - Docker container with docker_exec
    - Hydrated snapshot mounted at /snapshots/<slug>/

    Args:
        input_data: Grader input with critic_run_id
        client: OpenAI client
        hydrator: Snapshot hydrator for mounting snapshot source code
        canonical_tps: Canonical true positives (from DB or registry)
        canonical_fps: Known false positives (from DB or registry)
        db_config: Database configuration
        extra_handlers: Additional handlers
        verbose: Enable verbose output
        max_lines: Max lines for verbose display
        max_turns: Maximum agent turns before failure

    Returns:
        Grader run ID
    """
    # Generate unique IDs for this run
    run_id = uuid4()
    transcript_id = uuid4()

    # Phase 1: Write initial run and fetch critique (BEFORE agent runs)
    with get_session() as session:
        # Fetch critic run to get snapshot_slug
        critic_run = session.get(CriticRun, input_data.critic_run_id)
        if critic_run is None:
            raise ToolError(f"Critic run {input_data.critic_run_id} not found in database")

        snapshot_slug = critic_run.snapshot_slug

        # Build canonical issues snapshot for tracking (convert MCP models to DB models)
        canonical_snapshot = CanonicalIssuesSnapshot(
            true_positives=[tp_to_db(tp) for tp in canonical_tps],
            false_positives=[fp_to_db(fp) for fp in canonical_fps],
        )

        session.add(
            DBGraderRun(
                id=run_id,
                transcript_id=transcript_id,
                snapshot_slug=snapshot_slug,
                model=client.model,
                critic_run_id=input_data.critic_run_id,
                prompt_optimization_run_id=input_data.prompt_optimization_run_id,
                canonical_issues_snapshot=canonical_snapshot,
                status=GraderRunStatus.IN_PROGRESS,  # Will be updated to COMPLETED by submit
                # output left as None (nullable) - results are in grading_decisions table
            )
        )
        session.commit()
        logger.info(f"Created initial grader run in DB: {run_id=}, {transcript_id=}, snapshot_slug={snapshot_slug}")

    # Run agent via MCP-over-HTTP
    await _run_grader_agent(
        hydrator=hydrator,
        docker_client=docker_client,
        client=client,
        transcript_id=transcript_id,
        input_data=input_data,
        verbose=verbose,
        extra_handlers=extra_handlers,
        db_config=db_config,
        max_lines=max_lines,
        max_turns=max_turns,
        grader_run_id=run_id,
    )

    # Phase 2: Verify grader run was updated in database by submit server
    with get_session() as session:
        found_run = session.get(DBGraderRun, run_id)
        assert found_run is not None, f"Grader run {run_id} not found in database"
        logger.info(
            f"Grader run completed and written to DB: {transcript_id=}, snapshot_slug={snapshot_slug}, status={found_run.status}"
        )

    return run_id


async def grade_critic_run_by_id(
    session: Session,
    critic_run_id: UUID,
    client: OpenAIModelProto,
    docker_client: aiodocker.Docker,
    hydrator: SnapshotHydrator,
    db_config: DatabaseConfig,
    prompt_optimization_run_id: UUID | None = None,
    verbose: bool = False,
    max_turns: int = 200,
) -> UUID:
    """Grade critic run by ID, return grader_run_id.

    Args:
        session: Database session (caller manages transaction)
        critic_run_id: ID of critic run to grade
        client: OpenAI client
        docker_client: Async Docker client
        hydrator: Snapshot hydrator for mounting snapshot source code
        db_config: Database configuration
        prompt_optimization_run_id: Optional link to prompt optimization session
        verbose: Enable verbose output
        max_turns: Maximum agent turns before failure

    Returns:
        Grader run ID
    """
    # Fetch critic run to get snapshot_slug
    critic_run = session.get(CriticRun, critic_run_id)
    if critic_run is None:
        raise ValueError(f"Critic run {critic_run_id} not found in database")

    snapshot_slug = critic_run.snapshot_slug

    # Load snapshot and issues from database (no jsonnet!)
    snapshot = session.query(Snapshot).filter_by(slug=snapshot_slug).one()

    # Get critic scope from example and resolve to file set for filtering
    # Scope is stored in Example table and referenced via (snapshot_slug, scope_hash) FK
    critic_scope = critic_run.example_obj.scope

    # Resolve scope to file set for TP/FP filtering
    if isinstance(critic_scope, AllFilesScope):
        # Load all files with issues from snapshot
        reviewed_files = snapshot.files_with_issues()
        if not reviewed_files:
            raise ValueError(
                f"Snapshot '{snapshot_slug}' has no files with ground truth issues. Cannot use AllFilesScope."
            )
    else:
        # Type narrowing: must be ExplicitFileScope
        assert isinstance(critic_scope, ExplicitFileScope)
        reviewed_files = {Path(f) for f in critic_scope.files}

    # Filter ORM models - ORM occurrences are domain models, so we can use domain model helpers directly
    original_tp_count = len(snapshot.true_positives)
    filtered_orm_tps = [
        tp
        for tp in snapshot.true_positives
        if any(should_catch_occurrence(occ, reviewed_files) for occ in tp.occurrences)
    ]
    filtered_orm_fps = [
        fp
        for fp in snapshot.false_positives
        if any(should_show_fp_occurrence(occ, reviewed_files) for occ in fp.occurrences)
    ]

    # Raise error if no TPs are catchable from reviewed files
    if original_tp_count > 0 and len(filtered_orm_tps) == 0:
        raise ValueError(
            f"Cannot grade: 0/{original_tp_count} TPs catchable from reviewed files {sorted(str(f) for f in reviewed_files)}"
        )

    # Convert only filtered ORM models to MCP models
    canonical_tps = [_tp_from_orm(tp) for tp in filtered_orm_tps]
    canonical_fps = [_fp_from_orm(fp) for fp in filtered_orm_fps]

    # Create grader input
    grader_input = GraderInput(critic_run_id=critic_run_id, prompt_optimization_run_id=prompt_optimization_run_id)

    # Execute grader run with explicit canonical issues (hydrator provided by caller)
    return await run_grader(
        input_data=grader_input,
        client=client,
        hydrator=hydrator,
        canonical_tps=canonical_tps,
        canonical_fps=canonical_fps,
        docker_client=docker_client,
        db_config=db_config,
        verbose=verbose,
        max_turns=max_turns,
    )


# =============================================================================
# Grader Agent Environment (SQL Mode)
# =============================================================================


class GraderAgentEnvironment(AgentEnvironment):
    """Agent environment for SQL-based grader with grader_submit tool.

    Provides complete environment for grader agents:
    - Temporary database user with RLS scoping (grader_agent_{run_id})
    - HTTP MCP server with grader_submit tool
    - Docker container with docker_exec
    - Hydrated snapshot mounted at /snapshots/<slug>/

    Agent workflow:
    1. Reads critique and ground truth from PostgreSQL via psql
    2. Writes grading decisions directly to PostgreSQL
    3. Calls grader_submit tool via MCP-over-HTTP when done
    4. Submit validates decisions and marks run complete

    Usage:
        async with GraderAgentEnvironment(
            snapshot_slug="ducktape/2025-11-26-00",
            docker_client=docker_client,
            hydrator=hydrator,
            grader_run_id=run_id,
            critic_run_id=critic_run_id,
        ) as compositor:
            # Run grader agent
            ...
    """

    def __init__(
        self,
        snapshot_slug: SnapshotSlug,
        docker_client: aiodocker.Docker,
        hydrator: SnapshotHydrator,
        grader_run_id: UUID,
        critic_run_id: UUID,
        db_config: DatabaseConfig,
    ):
        """Create grader agent environment.

        Args:
            snapshot_slug: Snapshot slug to hydrate and mount
            docker_client: Async Docker client
            hydrator: Snapshot hydrator
            grader_run_id: UUID of the grader run (for RLS scoping)
            critic_run_id: UUID of the critic run being graded
            db_config: Database configuration (passed via DI)
        """
        # Store params needed by _make_mcp_server
        self._grader_run_id = grader_run_id
        self._critic_run_id = critic_run_id

        def make_user_manager() -> GraderUserManager:
            """Create temporary grader user with RLS scoping."""
            return GraderUserManager(db_config.admin, grader_run_id)

        super().__init__(
            docker_client=docker_client,
            user_manager_factory=make_user_manager,
            hydrator=hydrator,
            db_config=db_config,
            snapshot_slugs=[snapshot_slug],
            workspace_prefix="grader_workspace_",
        )

    def bootstrap_mcp_resources(self) -> Sequence[tuple[str, str]]:
        """Return MCP resources to read during bootstrap.

        Returns empty list - grader reads data directly from PostgreSQL.
        """
        return []

    def bootstrap_items(self, builder, runtime) -> list:
        """Build bootstrap items with database schema and CLI helper documentation.

        Includes:
        - Database ORM models (single source of truth for schema)
        - Grader decision helper functions

        Note: No MCP HTTP bootstrap since grader reads data directly from PostgreSQL.

        Args:
            builder: TypedBootstrapBuilder for generating typed tool calls
            runtime: Mounted runtime server (comp.runtime)

        Returns:
            List of FunctionCallItems to inject before agent sampling
        """
        return [
            # All package file reads (single call for efficiency)
            read_package_files_call(
                builder,
                runtime,
                [
                    # Database ORM models (single source of truth for schema)
                    ("adgn.props.db", ["models.py"]),
                    # Grader decision helper functions for Python API
                    ("adgn.props.grader", ["decision_helpers.py"]),
                ],
            )
        ]

    def _make_mcp_server(self, auth: AuthProvider) -> EnhancedFastMCP:
        """Create grader submit server.

        Called by PropertiesDockerCompositorHTTP after hydration completes.

        Args:
            auth: Auth provider for HTTP authentication

        Returns:
            GraderSubmitServerSQL configured for this grader run
        """
        return GraderSubmitServerSQL(grader_run_id=self._grader_run_id, critic_run_id=self._critic_run_id, auth=auth)

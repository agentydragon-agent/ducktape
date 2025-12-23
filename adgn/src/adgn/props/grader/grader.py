"""Grader agent execution and environment.

Runs the grader agent to evaluate critic output against ground truth.
Uses MCP-over-HTTP for agent communication.
"""

import logging
from pathlib import Path
from uuid import UUID, uuid4

import aiodocker
from fastmcp.client import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AuthProvider
from sqlalchemy.orm import Session

from adgn.agent.display import CompactDisplayHandler
from adgn.agent.handler import AbortIf, BaseHandler, RedirectOnTextMessageHandler
from adgn.agent.turn_limit import MaxTurnsExceededError, MaxTurnsHandler
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.openai_utils.model import OpenAIModelProto
from adgn.openai_utils.types import ReasoningSummary
from adgn.props.agent_handle import AgentHandle
from adgn.props.agent_setup import AgentEnvironment
from adgn.props.agent_types import CriticTypeConfig, GraderTypeConfig
from adgn.props.agent_workspace import WorkspaceManager
from adgn.props.cli.common_options import DEFAULT_MAX_LINES
from adgn.props.db import get_session
from adgn.props.db.agent_definition_ids import GRADER_AGENT_DEFINITION_ID
from adgn.props.db.config import DatabaseConfig
from adgn.props.db.models import AgentRun, AgentRunStatus, CanonicalIssuesSnapshot, FileSet, Snapshot
from adgn.props.display import short_uuid
from adgn.props.grader.exceptions import GraderDidNotSubmitError
from adgn.props.grader.models import FalsePositiveID, GraderInput, KnownFalsePositive, TruePositiveID, TruePositiveIssue
from adgn.props.grader.persistence import fp_to_db, tp_to_db
from adgn.props.grader.submit_server import GraderSubmitServer as GraderSubmitServerSQL
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import SnapshotSlug
from adgn.props.models.examples import SingleFileSetExample, WholeSnapshotExample
from adgn.props.models.true_positive import FalsePositiveOccurrence, LineRange, TruePositiveOccurrence
from adgn.props.rationale import Rationale

logger = logging.getLogger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================


def _convert_files_jsonb(files_jsonb: dict) -> dict[Path, list[LineRange] | None]:
    """Convert JSONB files dict to Pydantic-typed dict.

    JSONB format: {path_str: [{start_line: int, end_line: int}, ...] | null}
    Each element is a LineRange serialized as dict.

    Output format: {Path: list[LineRange] | None}
    """
    result: dict[Path, list[LineRange] | None] = {}
    for path_str, ranges in files_jsonb.items():
        if ranges is None:
            result[Path(path_str)] = None
        else:
            # Each element is a dict with start_line/end_line
            result[Path(path_str)] = [LineRange(**r) for r in ranges]
    return result


def _tp_occ_from_orm(orm_occ) -> TruePositiveOccurrence:
    """Convert ORM TruePositiveOccurrenceORM to Pydantic TruePositiveOccurrence."""
    return TruePositiveOccurrence(
        occurrence_id=orm_occ.occurrence_id,
        files=_convert_files_jsonb(orm_occ.files),
        note=orm_occ.note,
        expect_caught_from=orm_occ.expect_caught_from_set,  # Already converts to set[frozenset[Path]]
    )


def _fp_occ_from_orm(orm_occ) -> FalsePositiveOccurrence:
    """Convert ORM FalsePositiveOccurrenceORM to Pydantic FalsePositiveOccurrence."""
    return FalsePositiveOccurrence(
        occurrence_id=orm_occ.occurrence_id,
        files=_convert_files_jsonb(orm_occ.files),
        note=orm_occ.note,
        relevant_files=orm_occ.relevant_files_set,  # Already converts to set[Path]
    )


def _tp_from_orm(orm_tp) -> TruePositiveIssue:
    """Convert ORM TruePositive to grader representation (module-private)."""
    return TruePositiveIssue(
        id=TruePositiveID(orm_tp.tp_id),
        rationale=Rationale(orm_tp.rationale),
        occurrences=[_tp_occ_from_orm(occ) for occ in orm_tp.occurrences],
    )


def _fp_from_orm(orm_fp) -> KnownFalsePositive:
    """Convert ORM FalsePositive to grader representation (module-private)."""
    return KnownFalsePositive(
        id=FalsePositiveID(orm_fp.fp_id),
        rationale=Rationale(orm_fp.rationale),
        occurrences=[_fp_occ_from_orm(occ) for occ in orm_fp.occurrences],
    )


# =============================================================================
# Agent Execution
# =============================================================================


async def _run_grader_agent(
    *,
    hydrator: SnapshotHydrator,
    docker_client: aiodocker.Docker,
    client: OpenAIModelProto,
    agent_run_id: UUID,
    input_data: GraderInput,
    verbose: bool,
    extra_handlers: tuple[BaseHandler, ...],
    db_config: DatabaseConfig,
    workspace_manager: WorkspaceManager,
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
        agent_run_id: Agent run ID for event tracking
        input_data: Grader input with critic_run_id
        verbose: Enable verbose output
        extra_handlers: Additional handlers
        db_config: Database configuration
        workspace_manager: Workspace manager for agent workspace paths (DI)
        max_lines: Max lines for verbose display
        max_turns: Maximum agent turns before failure
        grader_run_id: UUID of the grader run
    """
    # Derive snapshot_slug and snapshot_split from input_data.critic_run_id (the graded critic run)
    with get_session() as session:
        critic_run = session.get(AgentRun, input_data.critic_run_id)
        if critic_run is None:
            raise ValueError(f"Critic run {input_data.critic_run_id} not found")

        # Get snapshot_slug from critic's type_config
        if not isinstance(critic_run.type_config, CriticTypeConfig):
            raise ValueError(
                f"Critic run {input_data.critic_run_id} has wrong type_config type: {type(critic_run.type_config)}"
            )
        snapshot_slug = critic_run.type_config.example.snapshot_slug

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
        workspace_manager=workspace_manager,
    )

    async with comp_ctx as compositor, Client(compositor) as mcp_client:
        # Define abort condition: check database status for grader completion
        def _grader_ready_state() -> bool:
            """Check if grader run is completed in database."""
            with get_session() as session:
                found_run = session.get(AgentRun, grader_run_id)
                return found_run is not None and found_run.status in (
                    AgentRunStatus.COMPLETED,
                    AgentRunStatus.MAX_TURNS_EXCEEDED,
                    AgentRunStatus.REPORTED_FAILURE,
                )

        # Build grader-specific handlers
        # NOTE: Do NOT call build_props_handlers() here - AgentHandle.create() already adds
        # DatabaseEventHandler. We only add CompactDisplayHandler if verbose is enabled.
        grader_handlers: list[BaseHandler] = [AbortIf(should_abort=_grader_ready_state)]
        if verbose:
            display_handler = await CompactDisplayHandler.from_compositor(
                compositor,
                max_lines=max_lines,
                prefix=f"[GRADER {short_uuid(agent_run_id)} {snapshot_split} {snapshot_slug}] ",
            )
            grader_handlers.append(display_handler)

        grader_handlers.extend(
            [
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

        # Create AgentHandle - handles definition loading, workspace, bootstrap, system prompt
        agent_handle = await AgentHandle.create(
            agent_run_id=grader_run_id,
            definition_id=GRADER_AGENT_DEFINITION_ID,
            model_client=client,
            mcp_client=mcp_client,
            compositor=compositor,
            workspace_manager=workspace_manager,
            handlers=grader_handlers,
            dynamic_instructions=compositor.render_agent_dynamic_instructions,
            parallel_tool_calls=True,
            reasoning_summary=ReasoningSummary.detailed,
        )

        try:
            await agent_handle.run()

            # Agent completed normally - validate database status
            with get_session() as session:
                found_run = session.get(AgentRun, grader_run_id)
                if found_run is None:
                    raise GraderDidNotSubmitError(f"Grader run {grader_run_id} not found in database")
                if found_run.status != AgentRunStatus.COMPLETED:
                    raise GraderDidNotSubmitError(
                        f"Grader run {grader_run_id} completed but status is {found_run.status}, expected COMPLETED"
                    )

            return
        except MaxTurnsExceededError:
            # Agent ran out of turns - mark as max_turns_exceeded in database
            # NOTE: max_turns_exceeded is taken as recall=0.0 (see query_builders.py:803-806)
            logger.warning(
                f"Grader hit max turns limit ({max_turns}) for {snapshot_slug}, "
                f"agent_run_id={short_uuid(grader_run_id)}"
            )
            with get_session() as session:
                found_run = session.get(AgentRun, grader_run_id)
                if found_run:
                    found_run.status = AgentRunStatus.MAX_TURNS_EXCEEDED
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
    workspace_manager: WorkspaceManager,
    parent_agent_run_id: UUID | None = None,
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
        workspace_manager: Workspace manager for agent workspace paths (DI)
        parent_agent_run_id: Optional parent agent run ID (e.g., prompt optimizer)
        extra_handlers: Additional handlers
        verbose: Enable verbose output
        max_lines: Max lines for verbose display
        max_turns: Maximum agent turns before failure

    Returns:
        Grader run ID
    """
    # Generate unique IDs for this run
    run_id = uuid4()
    agent_run_id = uuid4()

    # Phase 1: Write initial AgentRun and fetch critique (BEFORE agent runs)
    with get_session() as session:
        # Fetch critic run (AgentRun) to get snapshot_slug from type_config
        critic_run = session.get(AgentRun, input_data.critic_run_id)
        if critic_run is None:
            raise ToolError(f"Critic run {input_data.critic_run_id} not found in database")

        # Get snapshot_slug from critic's type_config
        if not isinstance(critic_run.type_config, CriticTypeConfig):
            raise ToolError(
                f"Critic run {input_data.critic_run_id} has unexpected type_config: {type(critic_run.type_config)}"
            )
        snapshot_slug = critic_run.type_config.example.snapshot_slug

        # Build canonical issues snapshot for tracking (convert MCP models to DB models)
        canonical_snapshot = CanonicalIssuesSnapshot(
            true_positives=[tp_to_db(tp) for tp in canonical_tps],
            false_positives=[fp_to_db(fp) for fp in canonical_fps],
        )

        # Store grader-specific config in type_config JSONB
        # Use mode="json" to ensure UUIDs are serialized as strings for JSONB storage
        type_config = GraderTypeConfig(
            graded_agent_run_id=input_data.critic_run_id, canonical_issues_snapshot=canonical_snapshot.model_dump()
        ).model_dump(mode="json")

        session.add(
            AgentRun(
                agent_run_id=run_id,
                agent_definition_id="grader",  # Fixed definition ID for grader runs
                parent_agent_run_id=parent_agent_run_id,
                model=client.model,
                type_config=type_config,
                status=AgentRunStatus.IN_PROGRESS,  # Will be updated to COMPLETED by submit
            )
        )
        session.commit()
        logger.info(f"Created initial grader run in DB: agent_run_id={run_id}, snapshot_slug={snapshot_slug}")

    # Run agent via MCP-over-HTTP
    await _run_grader_agent(
        hydrator=hydrator,
        docker_client=docker_client,
        client=client,
        agent_run_id=agent_run_id,
        input_data=input_data,
        verbose=verbose,
        extra_handlers=extra_handlers,
        db_config=db_config,
        workspace_manager=workspace_manager,
        max_lines=max_lines,
        max_turns=max_turns,
        grader_run_id=run_id,
    )

    # Phase 2: Verify grader run was updated in database by submit server
    with get_session() as session:
        found_run = session.get(AgentRun, run_id)
        assert found_run is not None, f"Grader run {run_id} not found in database"
        logger.info(
            f"Grader run completed and written to DB: agent_run_id={run_id}, snapshot_slug={snapshot_slug}, status={found_run.status}"
        )

    return run_id


async def grade_critic_run_by_id(
    session: Session,
    critic_run_id: UUID,
    client: OpenAIModelProto,
    docker_client: aiodocker.Docker,
    hydrator: SnapshotHydrator,
    db_config: DatabaseConfig,
    workspace_manager: WorkspaceManager,
    parent_agent_run_id: UUID | None = None,
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
        workspace_manager: Workspace manager for agent workspace paths (DI)
        parent_agent_run_id: Optional parent agent run ID (e.g., prompt optimizer)
        verbose: Enable verbose output
        max_turns: Maximum agent turns before failure

    Returns:
        Grader run ID
    """
    # Fetch critic run (AgentRun) to get snapshot_slug from type_config
    critic_run = session.get(AgentRun, critic_run_id)
    if critic_run is None:
        raise ValueError(f"Critic run {critic_run_id} not found in database")

    # Get snapshot_slug and example from critic's type_config
    if not isinstance(critic_run.type_config, CriticTypeConfig):
        raise ValueError(f"Critic run {critic_run_id} has wrong type_config type: {type(critic_run.type_config)}")

    example_spec = critic_run.type_config.example
    snapshot_slug = example_spec.snapshot_slug

    # Load snapshot and issues from database (no jsonnet!)
    snapshot = session.query(Snapshot).filter_by(slug=snapshot_slug).one()

    # Resolve scope to file set for TP/FP filtering
    if isinstance(example_spec, WholeSnapshotExample):
        # Load all files with issues from snapshot
        reviewed_files = snapshot.files_with_issues()
        if not reviewed_files:
            raise ValueError(
                f"Snapshot '{snapshot_slug}' has no files with ground truth issues. Cannot use whole snapshot scope."
            )
    else:
        # Type narrowing: must be SingleFileSetExample
        assert isinstance(example_spec, SingleFileSetExample)
        # Look up file set to get files
        file_set = (
            session.query(FileSet)
            .filter_by(snapshot_slug=example_spec.snapshot_slug, files_hash=example_spec.files_hash)
            .one()
        )
        reviewed_files = {Path(m.file_path) for m in file_set.members}

    # Filter ORM models using ORM occurrence properties for type conversion
    original_tp_count = len(snapshot.true_positives)
    filtered_orm_tps = [
        tp
        for tp in snapshot.true_positives
        if any(any(alt.issubset(reviewed_files) for alt in occ.expect_caught_from_set) for occ in tp.occurrences)
    ]
    filtered_orm_fps = [
        fp
        for fp in snapshot.false_positives
        if any(bool(occ.relevant_files_set & reviewed_files) for occ in fp.occurrences)
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
    grader_input = GraderInput(critic_run_id=critic_run_id)

    # Execute grader run with explicit canonical issues (hydrator provided by caller)
    return await run_grader(
        input_data=grader_input,
        client=client,
        hydrator=hydrator,
        canonical_tps=canonical_tps,
        canonical_fps=canonical_fps,
        docker_client=docker_client,
        db_config=db_config,
        workspace_manager=workspace_manager,
        parent_agent_run_id=parent_agent_run_id,
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
        workspace_manager: WorkspaceManager,
    ):
        """Create grader agent environment.

        Args:
            snapshot_slug: Snapshot slug to hydrate and mount
            docker_client: Async Docker client
            hydrator: Snapshot hydrator
            grader_run_id: UUID of the grader run (for RLS scoping)
            critic_run_id: UUID of the critic run being graded
            db_config: Database configuration (passed via DI)
            workspace_manager: Workspace manager for agent workspace paths
        """
        # Store params needed by _make_mcp_server
        self._grader_run_id = grader_run_id
        self._critic_run_id = critic_run_id

        super().__init__(
            definition_id=GRADER_AGENT_DEFINITION_ID,
            agent_run_id=grader_run_id,
            docker_client=docker_client,
            hydrator=hydrator,
            db_config=db_config,
            workspace_manager=workspace_manager,
            snapshot_slugs=[snapshot_slug],
        )

    def _make_mcp_server(self, auth: AuthProvider) -> EnhancedFastMCP:
        """Create grader submit server.

        Called by PropertiesDockerCompositorHTTP after hydration completes.

        Args:
            auth: Auth provider for HTTP authentication

        Returns:
            GraderSubmitServerSQL configured for this grader run
        """
        return GraderSubmitServerSQL(grader_run_id=self._grader_run_id, critic_run_id=self._critic_run_id, auth=auth)

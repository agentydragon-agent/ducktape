"""Main orchestrator for clustering agent workflow.

Creates a scoped database environment, mounts snapshot code, and runs a clustering
agent that groups unknown issues into named clusters using direct SQL access.

The agent has RLS-scoped database credentials (run_id encoded in username) and
uses SQL to record clustering decisions. Completion is detected automatically
when all unknowns are assigned.
"""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
import tempfile
from typing import Annotated, Literal
from uuid import UUID, uuid4

import aiodocker
from fastmcp.client import Client
from pydantic import BaseModel, Field
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from adgn.agent.agent import Agent
from adgn.agent.bootstrap import TypedBootstrapBuilder, read_package_file_call
from adgn.agent.handler import BaseHandler, RedirectOnTextMessageHandler, SequenceHandler
from adgn.agent.loop_control import Abort, AllowAnyToolOrTextMessage, InjectItems, LoopDecision, NoAction
from adgn.mcp._shared.mounted import Mounted
from adgn.mcp.exec.docker.server import ContainerExecServer
from adgn.openai_utils.client_factory import build_client
from adgn.openai_utils.model import FunctionCallItem
from adgn.props.agent_setup import build_props_handlers
from adgn.props.db import get_session
from adgn.props.db.clustering_models import ClusteringRun, UnknownAssignment, UnknownCluster
from adgn.props.db.clustering_user_manager import ClusteringUserManager
from adgn.props.db.config import DatabaseConfig
from adgn.props.db.models import GraderRun
from adgn.props.db.snapshots import DBGraderSuccess
from adgn.props.docker_env import PROPS_NETWORK_NAME, PropertiesDockerCompositor
from adgn.props.hydration import SnapshotHydrator, SnapshotSlug

logger = logging.getLogger(__name__)


# ============================================================================
# Outcome Models
# ============================================================================


class OutcomeSuccess(BaseModel):
    """Agent successfully clustered all unknowns."""

    kind: Literal["success"] = "success"
    total_unknowns: int
    clusters_created: int
    mapped_to_existing: int


class OutcomeIncomplete(BaseModel):
    """Agent terminated with unknowns remaining (unexpected)."""

    kind: Literal["incomplete"] = "incomplete"
    remaining_unknowns: int
    message: str


ClusteringOutcome = Annotated[OutcomeSuccess | OutcomeIncomplete, Field(discriminator="kind")]


class ClusteringResult(BaseModel):
    """Result from running clustering agent."""

    run_id: int
    transcript_id: UUID
    outcome: ClusteringOutcome


# ============================================================================
# Completion Handler
# ============================================================================


class ClusteringCompletionHandler(BaseHandler):
    """Check completion every turn and abort when all unknowns are assigned.

    Queries the database EVERY turn to check if all unknowns have been assigned.
    When complete, returns Abort to terminate the agent successfully.

    NO progress messages are injected - the agent can query progress itself if needed.
    """

    def __init__(self, run_id: int, db_config: DatabaseConfig):
        """Initialize completion handler.

        Args:
            run_id: Clustering run ID to monitor
            db_config: Database configuration for queries
        """
        self._run_id = run_id
        self._db_config = db_config
        self._engine: Engine | None = None

    def on_before_sample(self) -> LoopDecision:
        """Check completion before each sampling turn."""
        # Initialize engine on first use
        if self._engine is None:
            self._engine = create_engine(self._db_config.admin_url())

        # Query for remaining unknowns
        with Session(self._engine) as session:
            # Count total unknowns from all grader runs for this snapshot
            run = session.get(ClusteringRun, self._run_id)
            if not run:
                logger.warning(f"Clustering run {self._run_id} not found")
                return NoAction()

            snapshot_slug = run.snapshot_slug

            # Get total unknowns from grader runs
            result = session.execute(select(GraderRun).where(GraderRun.snapshot_slug == snapshot_slug))
            grader_runs = result.scalars().all()

            total_unknowns = sum(
                len(gr.output.unknowns) if isinstance(gr.output, DBGraderSuccess) else 0 for gr in grader_runs
            )

            if total_unknowns == 0:
                logger.info("No unknowns found for this snapshot")
                return Abort()

            # Count assigned unknowns (active, non-cancelled assignments)
            result = session.execute(
                select(UnknownAssignment).where(
                    UnknownAssignment.clustering_run_id == self._run_id, UnknownAssignment.cancelled_at.is_(None)
                )
            )
            assigned_count = len(result.scalars().all())

            remaining = total_unknowns - assigned_count

            logger.debug(f"Completion check: {assigned_count}/{total_unknowns} assigned, {remaining} remaining")

            if remaining == 0:
                logger.info("All unknowns assigned - terminating successfully")
                return Abort()

        return NoAction()

    def __del__(self):
        """Clean up database engine."""
        if self._engine is not None:
            self._engine.dispose()


# ============================================================================
# Bootstrap Helpers
# ============================================================================


def make_clustering_bootstrap_calls(
    builder: TypedBootstrapBuilder, runtime: Mounted[ContainerExecServer]
) -> list[FunctionCallItem]:
    """Build bootstrap calls for clustering agent.

    Provides:
    - System overview (snapshots, database, evaluation flow)
    - Clustering schema documentation (tables, RLS, constraints)
    - Example SQL query scripts

    Args:
        builder: Bootstrap builder for generating typed tool calls
        runtime: Mounted runtime server for reading package files
    """
    return [
        # System overview
        read_package_file_call(builder, runtime, "adgn.props.docs", "system_overview.md"),
        # Clustering schema (tables, RLS, constraints, query examples)
        read_package_file_call(builder, runtime, "adgn.props.clustering", "schema_docs.md"),
        # Example SQL query scripts (auto-detect run_id)
        read_package_file_call(builder, runtime, "adgn.props.clustering", "example_queries.py"),
    ]


# ============================================================================
# Main Orchestrator
# ============================================================================


async def run_clustering_agent(
    run_id: int,
    model: str,
    hydrator: SnapshotHydrator,
    docker_client: aiodocker.Docker,
    db_config: DatabaseConfig,
    output_dir: Path | None = None,
    verbose: bool = False,
) -> ClusteringResult:
    """Run clustering agent for a specific clustering run.

    Creates temporary PostgreSQL credentials with RLS-scoped access, hydrates
    and mounts the snapshot code, and runs an agent that clusters unknowns
    using direct SQL access.

    Args:
        run_id: Clustering run ID to process
        model: LLM model for clustering agent (e.g., "gpt-4o")
        hydrator: Snapshot hydrator (required)
        docker_client: Docker client (required)
        db_config: Database configuration (required, from CLI caller)
        output_dir: Output directory for workspace/logs (defaults to temp)
        verbose: Enable verbose logging

    Returns:
        ClusteringResult with outcome and statistics

    Raises:
        ValueError: If run_id doesn't exist or snapshot not found

    Example:
        result = await run_clustering_agent(
            run_id=42,
            model="gpt-4o",
            hydrator=hydrator,
            docker_client=docker_client,
        )

        if result.outcome.kind == "success":
            logger.info(f"Clustered {result.outcome.total_unknowns} unknowns")
    """
    transcript_id = uuid4()

    # Default arguments
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix=f"cluster_agent_run{run_id}_"))

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load clustering run from database
    with get_session() as session:
        run = session.get(ClusteringRun, run_id)
        if not run:
            raise ValueError(f"Clustering run {run_id} not found")
        snapshot_slug = run.snapshot_slug

        # Update transcript_id in database
        run.transcript_id = str(transcript_id)
        session.commit()

    logger.info(
        f"Starting clustering agent run {run_id} (transcript {transcript_id}): snapshot={snapshot_slug}, model={model}"
    )
    logger.info(f"Output directory: {output_dir}")

    # 2. Create scoped database user with RLS policies
    async with ClusteringUserManager(db_config.admin, run_id) as creds:
        # Container-to-container database access with scoped user credentials
        agent_db_container = db_config.for_container_user(creds)

        # 3. Hydrate snapshot and keep alive for Docker mounting
        logger.info(f"Hydrating snapshot {snapshot_slug}")

        # Compositor will handle snapshot hydration and mounting at /snapshots/<slug>/
        # 5. Create compositor with MCP servers
        async with PropertiesDockerCompositor(
            workspace_root=output_dir,
            docker_client=docker_client,
            mount_properties=False,  # Agent doesn't need property definitions
            hydrator=hydrator,
            snapshot_slugs=[SnapshotSlug(snapshot_slug)],  # Automatic snapshot mounting
            ephemeral=False,  # Keep container for debugging if needed
            workspace_mode="rw",  # Agent writes logs/output here
            db_conn=agent_db_container,  # Scoped database access
            network_mode=PROPS_NETWORK_NAME,  # For database access
        ) as comp:
            # 6. Set up handlers
            completion_handler = ClusteringCompletionHandler(run_id, db_config)

            # Bootstrap calls (inject schema docs and example scripts)
            builder = TypedBootstrapBuilder.for_server(comp.runtime.server)
            bootstrap_calls = make_clustering_bootstrap_calls(builder, comp.runtime)
            bootstrap = SequenceHandler([InjectItems(items=bootstrap_calls)])

            # Compose all handlers
            props_handlers = await build_props_handlers(
                transcript_id=transcript_id,
                verbose_prefix=f"[CLUSTER RUN={run_id}] " if verbose else None,
                compositor=comp,
            )

            handlers = [
                bootstrap,
                *props_handlers,
                completion_handler,  # Check completion every turn
                RedirectOnTextMessageHandler(
                    reminder_message=(
                        "You are a clustering agent working on grouping unknown issues. "
                        "Your task is not complete. Continue analyzing unknowns and recording "
                        "decisions in the database using SQL (via docker_exec with psql) or "
                        "the provided example_queries.py scripts. Do not send text messages - "
                        "execute tool calls to query the database, inspect code at /workspace, "
                        "and record clustering decisions via SQL INSERT/UPDATE statements. "
                        "The agent will automatically stop when all unknowns are assigned."
                    )
                ),
            ]

            # 7. System prompt (static file, no template rendering)
            system_prompt_path = Path(__file__).parent / "prompts" / "clustering_system.md"
            system_prompt = system_prompt_path.read_text()

            # 8. Create and run agent
            client = build_client(model)

            async with Client(comp) as mcp_client:

                async def get_instructions() -> str:
                    return system_prompt

                agent = await Agent.create(
                    mcp_client=mcp_client,
                    client=client,
                    handlers=handlers,
                    parallel_tool_calls=True,
                    dynamic_instructions=get_instructions,
                    tool_policy=AllowAnyToolOrTextMessage(),
                )

                logger.info("Starting agent execution")
                await agent.run()
                logger.info("Agent execution completed")

            # 9. Compute outcome
            outcome = _compute_outcome(run_id, db_config)

            return ClusteringResult(run_id=run_id, transcript_id=transcript_id, outcome=outcome)


def _compute_outcome(run_id: int, db_config: DatabaseConfig) -> ClusteringOutcome:
    """Compute final outcome from database state.

    Args:
        run_id: Clustering run ID
        db_config: Database configuration

    Returns:
        ClusteringOutcome (success or incomplete with stats)
    """
    engine = create_engine(db_config.admin_url())

    try:
        with Session(engine) as session:
            # Get run info
            run = session.get(ClusteringRun, run_id)
            if not run:
                return OutcomeIncomplete(remaining_unknowns=0, message=f"Clustering run {run_id} not found")

            snapshot_slug = run.snapshot_slug

            # Count total unknowns
            result = session.execute(select(GraderRun).where(GraderRun.snapshot_slug == snapshot_slug))
            grader_runs = result.scalars().all()

            total_unknowns = sum(
                len(gr.output.unknowns) if isinstance(gr.output, DBGraderSuccess) else 0 for gr in grader_runs
            )

            if total_unknowns == 0:
                # No unknowns to cluster
                return OutcomeSuccess(total_unknowns=0, clusters_created=0, mapped_to_existing=0)

            # Count assignments by type
            assignments_result = session.execute(
                select(UnknownAssignment).where(
                    UnknownAssignment.clustering_run_id == run_id, UnknownAssignment.cancelled_at.is_(None)
                )
            )
            assignments: list[UnknownAssignment] = list(assignments_result.scalars().all())

            assigned_count = len(assignments)
            remaining = total_unknowns - assigned_count

            # Count clusters created
            clusters_result = session.execute(select(UnknownCluster).where(UnknownCluster.clustering_run_id == run_id))
            clusters_created = len(clusters_result.scalars().all())

            # Count mapped to existing TPs/FPs
            mapped_to_existing = sum(1 for a in assignments if a.mapped_tp_id is not None or a.mapped_fp_id is not None)

            if remaining > 0:
                return OutcomeIncomplete(
                    remaining_unknowns=remaining, message=f"{remaining} unknowns not assigned (out of {total_unknowns})"
                )

            # Update run status
            run.status = "completed"
            run.completed_at = datetime.now()
            session.commit()

            return OutcomeSuccess(
                total_unknowns=total_unknowns, clusters_created=clusters_created, mapped_to_existing=mapped_to_existing
            )

    finally:
        engine.dispose()

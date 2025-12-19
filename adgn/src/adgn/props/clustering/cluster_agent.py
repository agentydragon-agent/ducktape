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
from fastmcp.server.auth import AuthProvider
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from adgn.agent.agent import Agent
from adgn.agent.bootstrap import TypedBootstrapBuilder, read_package_files_call
from adgn.agent.events import AssistantText
from adgn.agent.handler import BaseHandler, SequenceHandler
from adgn.agent.loop_control import Abort, AllowAnyToolOrTextMessage, InjectItems, LoopDecision, NoAction
from adgn.mcp._shared.mounted import Mounted
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.mcp.exec.docker.server import ContainerExecServer
from adgn.openai_utils.model import OpenAIModelProto, UserMessage
from adgn.props.agent_setup import AgentEnvironment, build_props_handlers
from adgn.props.clustering.user_manager import ClusteringUserManager
from adgn.props.db import get_session
from adgn.props.db.clustering_models import ClusteringRun, UnknownAssignment, UnknownCluster
from adgn.props.db.config import DatabaseConfig
from adgn.props.db.models import GraderRun, GraderRunStatus, GradingDecision
from adgn.props.hydration import SnapshotHydrator

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


class ClusteringHandler(BaseHandler):
    """Combined completion check and text redirect handler for clustering agent.

    On each turn:
    1. Check if all unknowns are assigned → Abort if done
    2. If agent sent text instead of tool calls → inject reminder with progress/examples

    Queries the database once per turn to get current progress.
    """

    def __init__(self, run_id: int):
        """Initialize handler.

        Args:
            run_id: Clustering run ID to monitor
        """
        self._run_id = run_id
        self._text_detected = False

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        """Mark that assistant text was detected."""
        self._text_detected = True

    def on_before_sample(self) -> LoopDecision:
        """Check completion and redirect text messages."""
        with get_session() as session:
            # Get run info
            run = session.get(ClusteringRun, self._run_id)
            if not run:
                logger.warning(f"Clustering run {self._run_id} not found")
                return NoAction()

            snapshot_slug = run.snapshot_slug

            # Count total unknowns (grading decisions with no TP match)
            total_unknowns = (
                session.scalar(
                    select(func.count())
                    .select_from(GradingDecision)
                    .join(GraderRun)
                    .where(
                        GraderRun.snapshot_slug == snapshot_slug,
                        GraderRun.status == GraderRunStatus.COMPLETED,
                        GradingDecision.target_tp_id.is_(None),
                    )
                )
                or 0
            )

            if total_unknowns == 0:
                logger.info("No unknowns found for this snapshot")
                return Abort()

            # Get assigned unknowns
            assigned_result = session.execute(
                select(UnknownAssignment).where(
                    UnknownAssignment.clustering_run_id == self._run_id, UnknownAssignment.cancelled_at.is_(None)
                )
            )
            assigned_keys = {(a.grader_run_id, a.unknown_id) for a in assigned_result.scalars().all()}
            assigned_count = len(assigned_keys)
            remaining = total_unknowns - assigned_count

            logger.info(
                f"Completion check: {assigned_count}/{total_unknowns} assigned, "
                f"{remaining} remaining (run_id={self._run_id})"
            )

            # Check completion
            if remaining == 0:
                logger.info("All unknowns assigned - terminating successfully")
                return Abort()

            # Check for text redirect
            if self._text_detected:
                self._text_detected = False
                message = self._build_reminder(session, snapshot_slug, assigned_keys, remaining, total_unknowns)
                return InjectItems(items=[UserMessage.text(message)])

        return NoAction()

    def _build_reminder(
        self, session: Session, snapshot_slug: str, assigned_keys: set[tuple[UUID, str]], remaining: int, total: int
    ) -> str:
        """Build reminder message with progress and example IDs."""
        # Get example unassigned unknowns (just IDs)
        unassigned_decisions = (
            session.execute(
                select(GradingDecision)
                .join(GraderRun)
                .where(
                    GraderRun.snapshot_slug == snapshot_slug,
                    GraderRun.status == GraderRunStatus.COMPLETED,
                    GradingDecision.target_tp_id.is_(None),
                )
                .limit(10)
            )
            .scalars()
            .all()
        )

        # Filter to unassigned and take first 5
        example_ids: list[str] = []
        for d in unassigned_decisions:
            if (d.grader_run_id, d.input_issue_id) in assigned_keys:
                continue
            if len(example_ids) >= 5:
                break
            example_ids.append(f"grading_decision.id={d.id} (input_issue_id={d.input_issue_id!r})")

        lines = [
            f"You have work remaining: {remaining}/{total} unknowns still need assignment.",
            "",
            "Do NOT send text messages. Instead, use tool calls to:",
            "1. Query the database for unknowns (via docker_exec with psql)",
            "2. Inspect code at /workspace to understand the issues",
            "3. Create clusters or map unknowns to existing TPs/FPs via SQL",
            "",
            "You will be automatically stopped when all unknowns are assigned.",
        ]

        if example_ids:
            lines.append("")
            lines.append(f"Example unassigned unknowns ({len(example_ids)} of {remaining}):")
            for eid in example_ids:
                lines.append(f"  - {eid}")

        return "\n".join(lines)


# ============================================================================
# Agent Environment
# ============================================================================


class ClusteringAgentEnvironment(AgentEnvironment):
    """Agent environment for clustering with direct SQL access.

    Provides complete environment for clustering agents:
    - Temporary database user with RLS scoping (clustering_agent_{run_id})
    - Docker container with docker_exec and psql access
    - No custom MCP servers (agent uses SQL directly for clustering decisions)

    Agent workflow:
    1. Queries database for unknowns (grading decisions with no TP match)
    2. Clusters unknowns by similarity using SQL
    3. Records clustering decisions in unknown_clusters and unknown_assignments tables
    4. Completion handler auto-terminates when all unknowns are assigned

    Usage:
        async with ClusteringAgentEnvironment(
            docker_client=docker_client,
            hydrator=hydrator,
            clustering_run_id=run_id,
            db_config=config,
        ) as compositor:
            # Run clustering agent
            ...
    """

    def __init__(
        self,
        docker_client: aiodocker.Docker,
        hydrator: SnapshotHydrator,
        clustering_run_id: int,
        db_config: DatabaseConfig,
    ):
        """Create clustering agent environment.

        Args:
            docker_client: Async Docker client
            hydrator: Snapshot hydrator
            clustering_run_id: Clustering run ID (for RLS scoping)
            db_config: Database configuration (passed via DI)
        """

        def make_user_manager() -> ClusteringUserManager:
            """Create temporary clustering user with RLS scoping."""
            return ClusteringUserManager(db_config.admin, clustering_run_id)

        super().__init__(
            docker_client=docker_client,
            user_manager_factory=make_user_manager,
            hydrator=hydrator,
            db_config=db_config,
            snapshot_slugs=[],  # Clustering doesn't need specific snapshots mounted
            workspace_prefix="clustering_workspace_",
            mount_properties=False,
        )

    def bootstrap_items(self, builder: TypedBootstrapBuilder, runtime: Mounted[ContainerExecServer]) -> list:
        """Build bootstrap items for clustering agent initialization.

        Includes:
        - System overview (snapshots, database, evaluation flow)
        - Clustering schema documentation (tables, RLS, constraints)
        - Example SQL query scripts

        Args:
            builder: Bootstrap builder for generating typed tool calls
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
                    # System overview
                    ("adgn.props.docs", ["system_overview.md"]),
                    # Clustering schema (tables, RLS, constraints, query examples)
                    ("adgn.props.clustering", ["schema_docs.md", "example_queries.py"]),
                ],
            )
        ]

    def _make_mcp_server(self, auth: AuthProvider) -> EnhancedFastMCP:
        """Create MCP server for clustering agent.

        Clustering uses SQL directly, so return a minimal stub server.

        Args:
            auth: Auth provider for HTTP authentication (unused)

        Returns:
            Minimal FastMCP server stub
        """
        return EnhancedFastMCP("clustering_stub")


# ============================================================================
# Main Orchestrator
# ============================================================================


async def run_clustering_agent(
    run_id: int,
    hydrator: SnapshotHydrator,
    docker_client: aiodocker.Docker,
    db_config: DatabaseConfig,
    client: OpenAIModelProto,
    output_dir: Path | None = None,
    verbose: bool = False,
) -> ClusteringResult:
    """Run clustering agent for a specific clustering run.

    Creates temporary PostgreSQL credentials with RLS-scoped access, hydrates
    and mounts the snapshot code, and runs an agent that clusters unknowns
    using direct SQL access.

    Args:
        run_id: Clustering run ID to process
        hydrator: Snapshot hydrator (required)
        docker_client: Docker client (required)
        db_config: Database configuration (required, from CLI caller)
        client: OpenAI client (required). Use client.model for model name.
        output_dir: Output directory for workspace/logs (defaults to temp)
        verbose: Enable verbose logging

    Returns:
        ClusteringResult with outcome and statistics

    Raises:
        ValueError: If run_id doesn't exist or snapshot not found

    Example:
        result = await run_clustering_agent(
            run_id=42,
            hydrator=hydrator,
            docker_client=docker_client,
            db_config=db_config,
            client=build_client("gpt-4o"),
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
        f"Starting clustering agent run {run_id} (transcript {transcript_id}): snapshot={snapshot_slug}, model={client.model}"
    )
    logger.info(f"Output directory: {output_dir}")

    # 2. Create agent environment with scoped database user and HTTP MCP server
    agent_env = ClusteringAgentEnvironment(
        docker_client=docker_client, hydrator=hydrator, clustering_run_id=run_id, db_config=db_config
    )

    async with agent_env as comp:
        # 3. Set up handlers
        # Bootstrap calls (inject schema docs and example scripts)
        builder = TypedBootstrapBuilder.for_server(comp.runtime.server)
        bootstrap_calls = agent_env.bootstrap_items(builder, comp.runtime)
        bootstrap = SequenceHandler([InjectItems(items=bootstrap_calls)])

        # Compose all handlers
        props_handlers = await build_props_handlers(
            transcript_id=transcript_id, verbose_prefix=f"[CLUSTER RUN={run_id}] " if verbose else None, compositor=comp
        )

        handlers = [
            bootstrap,
            *props_handlers,
            ClusteringHandler(run_id),  # Completion check + text redirect with progress
        ]

        # 4. System prompt (static file, no template rendering)
        system_prompt_path = Path(__file__).parent / "prompts" / "clustering_system.md"
        system_prompt = system_prompt_path.read_text()

        # 5. Create and run agent
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

        # 6. Compute outcome
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

            # Count total unknowns from completed grader runs (decisions with no TP match)
            total_unknowns = (
                session.scalar(
                    select(func.count())
                    .select_from(GradingDecision)
                    .join(GraderRun)
                    .where(
                        GraderRun.snapshot_slug == snapshot_slug,
                        GraderRun.status == GraderRunStatus.COMPLETED,
                        GradingDecision.target_tp_id.is_(None),
                    )
                )
                or 0
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

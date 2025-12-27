"""Main orchestrator for clustering agent workflow.

Creates a scoped database environment, mounts snapshot code, and runs a clustering
agent that groups unknown issues into named clusters using direct SQL access.

The agent has RLS-scoped database credentials (agent_run_id encoded in username) and
uses SQL to record clustering decisions. Completion is detected automatically
when all unknowns are assigned.
"""

from __future__ import annotations

import logging
from pathlib import Path
import tempfile
from typing import Annotated, Literal
from uuid import UUID, uuid4

import aiodocker
from fastmcp.client import Client
from fastmcp.server.auth import AuthProvider
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, exists, func, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Session, aliased

from agent_core.events import AssistantText
from agent_core.handler import BaseHandler
from agent_core.loop_control import Abort, InjectItems, LoopDecision, NoAction
from mcp_infra.display import CompactDisplayHandler
from mcp_infra.enhanced import EnhancedFastMCP
from openai_utils.model import OpenAIModelProto, UserMessage
from openai_utils.types import ReasoningSummary
from props.agent_handle import AgentHandle
from props.agent_setup import AgentEnvironment
from props.agent_types import AgentType, ClusteringTypeConfig
from props.agent_workspace import WorkspaceManager
from props.db.agent_definition_ids import CLUSTERING_AGENT_DEFINITION_ID
from props.db.clustering_models import UnknownAssignment, UnknownCluster
from props.db.config import DatabaseConfig
from props.db.models import AgentRun, AgentRunStatus, GradingDecision
from props.db.session import get_session
from props.display import short_uuid
from props.ids import SnapshotSlug

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

    agent_run_id: UUID
    outcome: ClusteringOutcome


# ============================================================================
# Completion Handler
# ============================================================================


class ClusteringHandler(BaseHandler):
    """Combined completion check and text redirect handler for clustering agent.

    On each turn:
    1. Check if all unknowns are assigned -> Abort if done
    2. If agent sent text instead of tool calls -> inject reminder with progress/examples

    Queries the database once per turn to get current progress.
    """

    def __init__(self, agent_run_id: UUID, snapshot_slug: SnapshotSlug):
        """Initialize handler.

        Args:
            agent_run_id: Clustering agent run ID to monitor
            snapshot_slug: Snapshot whose unknowns are being clustered
        """
        self._agent_run_id = agent_run_id
        self._snapshot_slug = snapshot_slug
        self._text_detected = False

    def on_assistant_text_event(self, evt: AssistantText) -> None:
        """Mark that assistant text was detected."""
        self._text_detected = True

    def on_before_sample(self) -> LoopDecision:
        """Check completion and redirect text messages."""
        with get_session() as session:
            snapshot_slug = self._snapshot_slug

            # Count total unknowns (grading decisions with no TP match)
            # Two-phase approach: first find grader run IDs, then query decisions
            # Graders don't have snapshot_slug directly - they reference a critic run via graded_agent_run_id.
            # The snapshot_slug is in the critic's type_config.
            critic_ref = aliased(AgentRun)
            grader_run_ids = [
                ar.agent_run_id
                for ar in session.query(AgentRun)
                .filter(
                    AgentRun.type_config["agent_type"].astext == AgentType.GRADER,
                    AgentRun.status == AgentRunStatus.COMPLETED,
                    exists().where(
                        critic_ref.agent_run_id == AgentRun.type_config["graded_agent_run_id"].astext.cast(PG_UUID),
                        critic_ref.type_config["example"]["snapshot_slug"].astext == snapshot_slug,
                    ),
                )
                .all()
            ]
            total_unknowns = (
                (
                    session.scalar(
                        select(func.count())
                        .select_from(GradingDecision)
                        .where(GradingDecision.agent_run_id.in_(grader_run_ids), GradingDecision.target_tp_id.is_(None))
                    )
                    or 0
                )
                if grader_run_ids
                else 0
            )

            if total_unknowns == 0:
                logger.info("No unknowns found for this snapshot")
                return Abort()

            assigned_result = session.execute(
                select(UnknownAssignment).where(
                    UnknownAssignment.agent_run_id == self._agent_run_id, UnknownAssignment.cancelled_at.is_(None)
                )
            )
            assigned_keys = {(a.grader_run_id, a.unknown_id) for a in assigned_result.scalars().all()}
            assigned_count = len(assigned_keys)
            remaining = total_unknowns - assigned_count

            logger.info(
                f"Completion check: {assigned_count}/{total_unknowns} assigned, "
                f"{remaining} remaining (agent_run_id={self._agent_run_id})"
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
        self,
        session: Session,
        snapshot_slug: SnapshotSlug,
        assigned_keys: set[tuple[UUID, str]],
        remaining: int,
        total: int,
    ) -> str:
        """Build reminder message with progress and example IDs."""
        # Get example unassigned unknowns (just IDs)
        # Two-phase: find grader run IDs, then query decisions
        # Graders don't have snapshot_slug directly - they reference a critic run via graded_agent_run_id.
        critic_ref = aliased(AgentRun)
        grader_run_ids = [
            ar.agent_run_id
            for ar in session.query(AgentRun)
            .filter(
                AgentRun.type_config["agent_type"].astext == AgentType.GRADER,
                AgentRun.status == AgentRunStatus.COMPLETED,
                exists().where(
                    critic_ref.agent_run_id == AgentRun.type_config["graded_agent_run_id"].astext.cast(PG_UUID),
                    critic_ref.type_config["example"]["snapshot_slug"].astext == snapshot_slug,
                ),
            )
            .all()
        ]
        unassigned_decisions = (
            (
                session.execute(
                    select(GradingDecision)
                    .where(GradingDecision.agent_run_id.in_(grader_run_ids), GradingDecision.target_tp_id.is_(None))
                    .limit(10)
                )
                .scalars()
                .all()
            )
            if grader_run_ids
            else []
        )

        # Filter to unassigned and take first 5
        example_ids: list[str] = []
        for d in unassigned_decisions:
            if (d.agent_run_id, d.input_issue_id) in assigned_keys:
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
    - Temporary database user with RLS scoping (clustering_agent_{agent_run_id})
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
            agent_run_id=agent_run_id,
            db_config=config,
            workspace_manager=workspace_manager,
        ) as compositor:
            # Run clustering agent
            ...
    """

    def __init__(
        self,
        docker_client: aiodocker.Docker,
        agent_run_id: UUID,
        db_config: DatabaseConfig,
        workspace_manager: WorkspaceManager,
    ):
        """Create clustering agent environment.

        Args:
            docker_client: Async Docker client
            agent_run_id: Agent run ID (for RLS scoping)
            db_config: Database configuration (passed via DI)
            workspace_manager: Workspace manager for agent workspace paths
        """
        super().__init__(
            definition_id=CLUSTERING_AGENT_DEFINITION_ID,
            agent_run_id=agent_run_id,
            docker_client=docker_client,
            db_config=db_config,
            workspace_manager=workspace_manager,
            container_name=f"clustering-{short_uuid(agent_run_id)}",
            labels={"adgn.project": "props", "adgn.role": "clustering", "adgn.agent_run_id": str(agent_run_id)},
            auto_remove=True,
        )

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
    snapshot_slug: SnapshotSlug,
    docker_client: aiodocker.Docker,
    db_config: DatabaseConfig,
    client: OpenAIModelProto,
    agent_run_id: UUID | None = None,
    output_dir: Path | None = None,
    verbose: bool = False,
) -> ClusteringResult:
    """Run clustering agent for a snapshot.

    Creates an AgentRun with ClusteringTypeConfig, temporary PostgreSQL credentials
    with RLS-scoped access, and runs an agent that clusters unknowns using direct
    SQL access.

    Args:
        snapshot_slug: Snapshot whose unknowns to cluster
        docker_client: Docker client (required)
        db_config: Database configuration (required, from CLI caller)
        client: OpenAI client (required). Use client.model for model name.
        agent_run_id: Optional agent run ID (for resuming). If None, creates new run.
        output_dir: Output directory for workspace/logs (defaults to temp)
        verbose: Enable verbose logging

    Returns:
        ClusteringResult with outcome and statistics

    Raises:
        ValueError: If agent_run_id is provided but doesn't exist or has wrong type

    Example:
        result = await run_clustering_agent(
            snapshot_slug=SnapshotSlug("ducktape/2025-11-20-00"),
            docker_client=docker_client,
            db_config=db_config,
            client=build_client("gpt-4o"),
        )

        if result.outcome.kind == "success":
            logger.info(f"Clustered {result.outcome.total_unknowns} unknowns")
    """
    # Default arguments
    if agent_run_id is None:
        agent_run_id = uuid4()

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix=f"cluster_agent_{agent_run_id}_"))

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create or validate AgentRun
    with get_session() as session:
        existing_run = session.get(AgentRun, agent_run_id)
        if existing_run:
            # Resuming existing run - validate it
            if not isinstance(existing_run.type_config, ClusteringTypeConfig):
                raise ValueError(f"Agent run {agent_run_id} is not a clustering run")
            if existing_run.status != AgentRunStatus.IN_PROGRESS:
                raise ValueError(f"Agent run {agent_run_id} has status {existing_run.status}, expected 'in_progress'")
            # Validate snapshot matches
            if existing_run.type_config.snapshot_slug != snapshot_slug:
                raise ValueError(
                    f"Agent run {agent_run_id} is for {existing_run.type_config.snapshot_slug}, not {snapshot_slug}"
                )
        else:
            # Create new run
            type_config = ClusteringTypeConfig(snapshot_slug=snapshot_slug)
            agent_run = AgentRun(
                agent_run_id=agent_run_id,
                agent_definition_id=CLUSTERING_AGENT_DEFINITION_ID,
                model=client.model,
                type_config=type_config,
                status=AgentRunStatus.IN_PROGRESS,
            )
            session.add(agent_run)
            session.commit()

    logger.info(f"Starting clustering agent run {agent_run_id}: snapshot={snapshot_slug}, model={client.model}")
    logger.info(f"Output directory: {output_dir}")

    # 2. Create agent environment with scoped database user and HTTP MCP server
    workspace_manager = WorkspaceManager.from_env()
    agent_env = ClusteringAgentEnvironment(
        docker_client=docker_client, agent_run_id=agent_run_id, db_config=db_config, workspace_manager=workspace_manager
    )

    async with agent_env as comp, Client(comp) as mcp_client:
        # 3. Set up handlers
        # NOTE: Do NOT call build_props_handlers() here - AgentHandle.create() already adds
        # DatabaseEventHandler. We only add CompactDisplayHandler if verbose is enabled.
        handlers: list[BaseHandler] = []
        if verbose:
            display_handler = await CompactDisplayHandler.from_compositor(comp, prefix=f"[CLUSTER {agent_run_id}] ")
            handlers.append(display_handler)

        handlers.append(
            ClusteringHandler(agent_run_id, snapshot_slug)
        )  # Completion check + text redirect with progress

        # 4. Create AgentHandle - reads system prompt from container via MCP, runs init
        agent_handle = await AgentHandle.create(
            agent_run_id=agent_run_id,
            definition_id=CLUSTERING_AGENT_DEFINITION_ID,
            model_client=client,
            mcp_client=mcp_client,
            compositor=comp,
            handlers=handlers,
            dynamic_instructions=comp.render_agent_dynamic_instructions,
            parallel_tool_calls=True,
            reasoning_summary=ReasoningSummary.DETAILED,
        )

        logger.info("Starting agent execution")
        await agent_handle.run()
        logger.info("Agent execution completed")

        # 6. Compute outcome
        outcome = _compute_outcome(agent_run_id, snapshot_slug, db_config)

        return ClusteringResult(agent_run_id=agent_run_id, outcome=outcome)


def _compute_outcome(agent_run_id: UUID, snapshot_slug: SnapshotSlug, db_config: DatabaseConfig) -> ClusteringOutcome:
    """Compute final outcome from database state.

    Args:
        agent_run_id: Clustering agent run ID
        snapshot_slug: Snapshot whose unknowns were clustered
        db_config: Database configuration

    Returns:
        ClusteringOutcome (success or incomplete with stats)
    """
    engine = create_engine(db_config.admin_url())

    try:
        with Session(engine) as session:
            # Count total unknowns from completed grader runs (decisions with no TP match)
            # Two-phase: find grader run IDs, then query decisions
            # Graders don't have snapshot_slug directly - they reference a critic run via graded_agent_run_id.
            critic_ref = aliased(AgentRun)
            grader_run_ids = [
                ar.agent_run_id
                for ar in session.query(AgentRun)
                .filter(
                    AgentRun.type_config["agent_type"].astext == AgentType.GRADER,
                    AgentRun.status == AgentRunStatus.COMPLETED,
                    exists().where(
                        critic_ref.agent_run_id == AgentRun.type_config["graded_agent_run_id"].astext.cast(PG_UUID),
                        critic_ref.type_config["example"]["snapshot_slug"].astext == snapshot_slug,
                    ),
                )
                .all()
            ]
            total_unknowns = (
                (
                    session.scalar(
                        select(func.count())
                        .select_from(GradingDecision)
                        .where(GradingDecision.agent_run_id.in_(grader_run_ids), GradingDecision.target_tp_id.is_(None))
                    )
                    or 0
                )
                if grader_run_ids
                else 0
            )

            if total_unknowns == 0:
                # No unknowns to cluster
                return OutcomeSuccess(total_unknowns=0, clusters_created=0, mapped_to_existing=0)

            # Count assignments by type
            assignments_result = session.execute(
                select(UnknownAssignment).where(
                    UnknownAssignment.agent_run_id == agent_run_id, UnknownAssignment.cancelled_at.is_(None)
                )
            )
            assignments: list[UnknownAssignment] = list(assignments_result.scalars().all())

            assigned_count = len(assignments)
            remaining = total_unknowns - assigned_count

            # Count clusters created
            clusters_result = session.execute(select(UnknownCluster).where(UnknownCluster.agent_run_id == agent_run_id))
            clusters_created = len(clusters_result.scalars().all())

            # Count mapped to existing TPs/FPs
            mapped_to_existing = sum(1 for a in assignments if a.mapped_tp_id is not None or a.mapped_fp_id is not None)

            if remaining > 0:
                return OutcomeIncomplete(
                    remaining_unknowns=remaining, message=f"{remaining} unknowns not assigned (out of {total_unknowns})"
                )

            # Update run status
            run = session.get(AgentRun, agent_run_id)
            if run:
                run.status = AgentRunStatus.COMPLETED
                session.commit()

            return OutcomeSuccess(
                total_unknowns=total_unknowns, clusters_created=clusters_created, mapped_to_existing=mapped_to_existing
            )

    finally:
        engine.dispose()

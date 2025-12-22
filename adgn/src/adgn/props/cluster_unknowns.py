import asyncio
from collections import defaultdict
import json
import logging
from pathlib import Path
from uuid import UUID

from fastmcp.client import Client
from pydantic import BaseModel, ConfigDict, Field

from adgn.agent.agent import Agent
from adgn.agent.handler import AbortIf
from adgn.agent.loop_control import RequireAnyTool
from adgn.agent.transcript_handler import TranscriptHandler
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.openai_utils.client_factory import build_client
from adgn.openai_utils.model import SystemMessage, UserMessage
from adgn.props.agent_types import AgentType
from adgn.props.db import get_session
from adgn.props.db.models import AgentRun, AgentRunStatus, GradingDecision, ReportedIssue
from adgn.props.rationale import Rationale
from adgn.props.runs_context import RunsContext, format_timestamp_session

logger = logging.getLogger(__name__)

# MCP mount prefix for cluster submission server
CLUSTER_SUBMIT_MOUNT_PREFIX = "cluster_submit"


class ClusteredIssueID(BaseModel):
    """Unique identifier for an issue within a critic run (critic_run_id, tp_id)."""

    critic_run_id: UUID
    tp_id: str  # Issue ID string (from reported issues table)

    model_config = ConfigDict(frozen=True)


class UnknownIssue(BaseModel):
    """Structured view of a single unknown issue extracted from grader runs."""

    tp_id: ClusteredIssueID
    rationale: Rationale
    files: set[Path]


class ClusterSpec(BaseModel):
    name: str
    issue_ids: list[ClusteredIssueID]
    primary_files: set[Path] = Field(
        description="Files affected by issues in this cluster (aggregated from all occurrences)"
    )


class ClusterSubmitPayload(BaseModel):
    clusters: list[ClusterSpec]


def _extract_unknowns_from_run(session, db_run: AgentRun, reported_issues: list) -> list[UnknownIssue]:
    """Extract unknown issues from a single grader run.

    Returns empty list if critic result is not complete or if no novel issues found.
    """
    # Skip grader runs that didn't complete successfully
    if db_run.status != AgentRunStatus.COMPLETED:
        return []

    # Query grading decisions with no TP match (unknowns)
    unknown_decisions = (
        session.query(GradingDecision)
        .filter_by(agent_run_id=db_run.agent_run_id)
        .filter(GradingDecision.target_tp_id.is_(None))
        .all()
    )

    if not unknown_decisions:
        return []

    # Build a map of issue_id -> ReportedIssue for quick lookup
    issues_by_id = {issue.issue_id: issue for issue in reported_issues}

    # Get critic run ID from grader's type_config
    graded_critic_run_id = db_run.grader_config().graded_agent_run_id

    # Extract unknown issues (build from grading decisions)
    return [
        UnknownIssue(
            tp_id=ClusteredIssueID(critic_run_id=graded_critic_run_id, tp_id=decision.input_issue_id),
            rationale=Rationale(matching_issue.rationale),
            files={Path(loc.file) for occ in matching_issue.occurrences for loc in occ.locations},
        )
        for decision in unknown_decisions
        if decision.input_issue_id is not None
        and (matching_issue := issues_by_id.get(decision.input_issue_id)) is not None
    ]


async def _cluster_snapshot(snapshot_issues: list[UnknownIssue], out_root: Path, model: str) -> None:
    """Run clustering agent for a single snapshot."""
    out_root.mkdir(parents=True, exist_ok=True)
    result: list[ClusterSpec] | None = None

    # Use Compositor as async context manager to ensure cleanup
    async with Compositor() as comp:
        srv = EnhancedFastMCP("cluster_submit", instructions="Cluster submit")

        @srv.tool()
        def submit_result(payload: ClusterSubmitPayload) -> str:
            nonlocal result
            seen = {it for c in payload.clusters for it in c.issue_ids}
            all_keys = {u.tp_id for u in snapshot_issues}
            missing = sorted(all_keys - seen, key=lambda x: (x.critic_run_id, x.tp_id))
            if missing:
                raise ValueError(f"missing {len(missing)} issue(s) in clusters; first: {missing[:3]}")

            # Compute primary_files for each cluster by aggregating from issues
            issue_lookup = {u.tp_id: u for u in snapshot_issues}
            enriched_clusters = []
            for cluster in payload.clusters:
                primary_files = set()
                for issue_id in cluster.issue_ids:
                    if issue_id in issue_lookup:
                        primary_files.update(issue_lookup[issue_id].files)
                enriched_clusters.append(
                    ClusterSpec(name=cluster.name, issue_ids=cluster.issue_ids, primary_files=primary_files)
                )
            result = enriched_clusters
            return "ok"

        await comp.mount_inproc(CLUSTER_SUBMIT_MOUNT_PREFIX, srv)
        system = "Cluster semantically equivalent issues. Reference issues by their tp_id."
        input_lines = "\n".join(json.dumps(i.model_dump(mode="json"), ensure_ascii=False) for i in snapshot_issues)
        user_prompt = "Cluster the following issues. Every tp_id must appear in >=1 cluster.\n\n" + input_lines
        async with Client(comp) as mcp_client:
            agent = await Agent.create(
                mcp_client=mcp_client,
                client=build_client(model),
                handlers=[
                    TranscriptHandler(events_path=out_root / "events.jsonl"),
                    AbortIf(should_abort=lambda: result is not None),
                ],
                dynamic_instructions=comp.render_agent_dynamic_instructions,
                parallel_tool_calls=True,
                tool_policy=RequireAnyTool(),
            )
            agent.insert_messages([SystemMessage.text(system), UserMessage.text(user_prompt)])
            await agent.run()
    # Compositor.__aexit__ unmounts all non-pinned servers and cleans up containers here

    if result is None:
        raise RuntimeError("cluster_submit.submit_result not called")
    (out_root / "clusters.json").write_text(
        json.dumps([c.model_dump(mode="json") for c in result], indent=2), encoding="utf-8"
    )


async def cluster_unknowns(*, model: str = "gpt-5", out_dir: Path | None = None, ctx: RunsContext) -> Path:
    """Cluster unknowns per snapshot in parallel using an LLM (one run per snapshot).

    Loads unknown issues from grader runs in the database (using Pydantic).
    Partitions unknowns by snapshot and launches an in-proc MCP clustering agent per snapshot concurrently.
    Each snapshot writes clusters.json under runs/cluster/<ts>/{snapshot}/.
    """
    # Load unknown issues from grader runs in database, partitioned by snapshot
    by_spec: dict[str, list[UnknownIssue]] = defaultdict(list)
    with get_session() as session:
        # Load grader runs and their reported issues
        # Query grader runs that completed successfully (via AgentRun with JSONB filter)
        grader_runs = (
            session.query(AgentRun)
            .filter(
                AgentRun.type_config["agent_type"].astext == AgentType.GRADER,
                AgentRun.status == AgentRunStatus.COMPLETED,
            )
            .all()
        )

        for db_run in grader_runs:
            # Load reported issues for this grader's critic run
            graded_critic_run_id = db_run.grader_config().graded_agent_run_id
            reported_issues = session.query(ReportedIssue).filter_by(agent_run_id=graded_critic_run_id).all()

            # Get snapshot_slug from the critic run's type_config
            critic_run = session.get(AgentRun, graded_critic_run_id)
            if not critic_run:
                raise ValueError(f"Critic run {graded_critic_run_id} not found for grader {db_run.agent_run_id}")
            snapshot_slug = critic_run.critic_config().snapshot_slug
            by_spec[snapshot_slug].extend(_extract_unknowns_from_run(session, db_run, reported_issues))

    if not by_spec:
        raise RuntimeError("no unknown issues found in grader runs in database")
    if out_dir is not None:
        root: Path = Path(out_dir).expanduser().resolve()
    else:
        root = ctx.base_dir / "cluster" / format_timestamp_session()
    root.mkdir(parents=True, exist_ok=True)

    # Run clustering tasks in parallel (one per snapshot)
    await asyncio.gather(*(_cluster_snapshot(items, root / spec, model) for spec, items in by_spec.items()))
    return root

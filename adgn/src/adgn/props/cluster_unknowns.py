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
from adgn.props.db import get_session
from adgn.props.db.models import Critique, GraderRun
from adgn.props.rationale import Rationale
from adgn.props.runs_context import RunsContext, format_timestamp_session

logger = logging.getLogger(__name__)

# MCP mount prefix for cluster submission server
CLUSTER_SUBMIT_MOUNT_PREFIX = "cluster_submit"


class ClusteredIssueID(BaseModel):
    """Unique identifier for an issue within a critique (critique_id, tp_id)."""

    critique_id: UUID
    tp_id: str  # Issue ID string (from DB model)

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


def _extract_unknowns_from_run(db_run: GraderRun, critique: Critique) -> list[UnknownIssue]:
    """Extract unknown issues from a single grader run.

    Returns empty list if critic result is not success or if no novel issues found.
    """
    # Skip grader runs where output is None (incomplete/failed runs)
    if db_run.output is None:
        return []

    # Use DB models directly (no conversion needed)
    critique_payload_db = critique.payload
    critique_id = db_run.critique_id

    # Extract unknown issues (access nested fields directly from DB models)
    return [
        UnknownIssue(
            tp_id=ClusteredIssueID(critique_id=critique_id, tp_id=entry.input_id),
            rationale=Rationale(matching_issue.rationale),
            files={Path(fo.path) for occ in matching_issue.occurrences for fo in occ.files},
        )
        for entry in db_run.output.novel_critique_issues
        if (matching_issue := next((issue for issue in critique_payload_db.issues if issue.id == entry.input_id), None))
        is not None
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
            missing = sorted(all_keys - seen, key=lambda x: (x.critique_id, x.tp_id))
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
        results = (
            session.query(GraderRun, Critique)
            .join(Critique, GraderRun.critique_id == Critique.id)
            .filter(GraderRun.output.is_not(None))
            .all()
        )
        for db_run, critique in results:
            by_spec[db_run.snapshot_slug].extend(_extract_unknowns_from_run(db_run, critique))

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

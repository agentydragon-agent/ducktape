import asyncio
from collections import defaultdict
import json
import logging
from pathlib import Path
from uuid import UUID

from fastmcp.client import Client
from pydantic import BaseModel, ConfigDict

from adgn.agent.agent import MiniCodex
from adgn.agent.loop_control import RequireAnyTool
from adgn.agent.reducer import AbortIf
from adgn.agent.transcript_handler import TranscriptHandler
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.openai_utils.client_factory import build_client
from adgn.props.critic.models import CriticSubmitPayload
from adgn.props.db import get_session
from adgn.props.db.models import Critique, GraderRun
from adgn.props.grader.models import GraderOutput
from adgn.props.ids import BaseIssueID
from adgn.props.rationale import Rationale
from adgn.props.runs_context import RunsContext, format_timestamp_session

logger = logging.getLogger(__name__)


class ClusteredIssueID(BaseModel):
    """Unique identifier for an issue within a critique (critique_id, tp_id)."""

    critique_id: UUID
    tp_id: BaseIssueID

    model_config = ConfigDict(frozen=True)


class UnknownIssue(BaseModel):
    """Structured view of a single unknown issue extracted from grader runs."""

    tp_id: ClusteredIssueID
    rationale: Rationale
    files: set[Path]


class ClusterSpec(BaseModel):
    name: str
    issue_ids: list[ClusteredIssueID]


class ClusterSubmitPayload(BaseModel):
    clusters: list[ClusterSpec]


def _extract_unknowns_from_run(db_run: GraderRun, critique: Critique) -> list[UnknownIssue]:
    """Extract unknown issues from a single grader run.

    Returns empty list if critic result is not success or if no novel issues found.
    """
    # Skip runs with no output (failed/incomplete runs)
    if db_run.output is None:
        return []

    # Parse typed output from JSONB
    grader_output = GraderOutput.model_validate(db_run.output)
    critique_payload = CriticSubmitPayload.model_validate(critique.payload)

    critique_id = db_run.critique_id

    # Extract unknown issues
    return [
        UnknownIssue(
            tp_id=ClusteredIssueID(critique_id=critique_id, tp_id=input_id),
            rationale=matching_issue.rationale,
            files={f for occ in matching_issue.occurrences for f in occ.files},
        )
        for input_id in grader_output.grade.novel_critique_issues
        if (matching_issue := next((issue for issue in critique_payload.issues if issue.id == str(input_id)), None))
        is not None
    ]


async def _cluster_snapshot(snapshot_issues: list[UnknownIssue], out_root: Path, model: str) -> None:
    """Run clustering agent for a single snapshot."""
    out_root.mkdir(parents=True, exist_ok=True)
    result: list[ClusterSpec] | None = None

    comp = Compositor("compositor")
    srv = NotifyingFastMCP("cluster_submit", instructions="Cluster submit")

    @srv.tool()
    def submit_result(payload: ClusterSubmitPayload) -> str:
        nonlocal result
        seen = {it for c in payload.clusters for it in c.issue_ids}
        all_keys = {u.tp_id for u in snapshot_issues}
        missing = sorted(all_keys - seen, key=lambda x: (x.critique_id, x.tp_id))
        if missing:
            raise ValueError(f"missing {len(missing)} issue(s) in clusters; first: {missing[:3]}")
        result = payload.clusters
        return "ok"

    await comp.mount_inproc("cluster_submit", srv)
    system = "Cluster semantically equivalent issues. Reference issues by their tp_id."
    input_lines = "\n".join(json.dumps(i.model_dump(mode="json"), ensure_ascii=False) for i in snapshot_issues)
    async with Client(comp) as mcp_client:
        agent = await MiniCodex.create(
            mcp_client=mcp_client,
            system=system,
            client=build_client(model),
            handlers=[
                TranscriptHandler(events_path=out_root / "events.jsonl"),
                AbortIf(should_abort=lambda: result is not None),
            ],
            parallel_tool_calls=True,
            tool_policy=RequireAnyTool(),
        )
        await agent.run("Cluster the following issues. Every tp_id must appear in >=1 cluster.\n\n" + input_lines)
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
        # Join GraderRun with Critique to avoid N+1 queries
        results = session.query(GraderRun, Critique).join(Critique, GraderRun.critique_id == Critique.id).all()
        for db_run, critique in results:
            by_spec[db_run.snapshot_slug].extend(_extract_unknowns_from_run(db_run, critique))

    if not by_spec:
        raise RuntimeError("no unknown issues found in grader runs in database")
    if out_dir is not None:
        root: Path = Path(out_dir).expanduser().resolve()
    else:
        # Inline cluster_output_dir (only called here)
        timestamp = format_timestamp_session()
        root = ctx.base_dir / "cluster" / timestamp
    root.mkdir(parents=True, exist_ok=True)

    # Run clustering tasks in parallel (one per snapshot)
    tasks = []
    for spec, items in by_spec.items():
        out_spec = root / spec
        tasks.append(_cluster_snapshot(items, out_spec, model))
    await asyncio.gather(*tasks)
    return root

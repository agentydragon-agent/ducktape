import asyncio
from collections.abc import Iterable
from datetime import datetime
import json
import logging
from pathlib import Path

from fastmcp.client import Client
from pydantic import BaseModel, Field

from adgn.agent.agent import MiniCodex
from adgn.agent.reducer import GateUntil
from adgn.agent.transcript_handler import TranscriptHandler
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP  # type: ignore
from adgn.openai_utils.client_factory import build_client
from adgn.openai_utils.model import OpenAIModelProto
from adgn.props.ids import BaseIssueID
from adgn.props.prop_utils import pkg_dir
from adgn.props.rationale import Rationale
from adgn.props.run_models import GraderInput, GraderOutput, SpecimenScope

logger = logging.getLogger(__name__)


class UnknownIssue(BaseModel):
    """Structured view of a single unknown issue extracted from grader runs."""

    specimen: str
    id: BaseIssueID
    should_flag: bool | None = None
    rationale: Rationale
    files: set[str]
    run_path: Path = Field(..., description="Path to grader run directory for provenance")


class ClusterSpec(BaseModel):
    name: str
    issues: list[str]


class ClusterSubmitPayload(BaseModel):
    clusters: list[ClusterSpec]


class ClusterSubmitState:
    def __init__(self) -> None:
        self.result: list[ClusterSpec] | None = None


def discover_grader_runs(runs_dir: Path) -> list[Path]:
    """Find all grader run directories under the runs structure.

    New path structure: {runs_dir}/{split}/grader/{scope_id}/{timestamp}/
    Example: runs/train/grader/specimen:ducktape/2025-11-26-00/20250127T153045/

    Args:
        runs_dir: Base runs directory (should be passed from caller, not computed here)

    Returns:
        List of run directories (each containing input.json and output.json).
    """
    # Search pattern: runs/*/grader/*/*/output.json
    # - First * = split (train/valid/test)
    # - Second through fourth * = scope_id path components + timestamp
    output_files = sorted(runs_dir.rglob("*/grader/*/*/output.json"))
    # Return parent directories (the run dirs)
    return [f.parent for f in output_files]


def load_unknowns(run_dirs: Iterable[Path]) -> list[UnknownIssue]:
    """Load unknown issues from grader run directories using Pydantic models.

    Loads typed input.json (GraderInput) and output.json (GraderOutput) from each run.
    Extracts specimen from input.scope, unknown issues from output.grade.novel_critique_issues.

    Args:
        run_dirs: Grader run directories (each containing input.json and output.json)

    Returns:
        List of UnknownIssue objects ready for clustering
    """
    issues: list[UnknownIssue] = []

    for run_dir in run_dirs:
        try:
            # Load typed input to get specimen
            grader_input = GraderInput.model_validate_json((run_dir / "input.json").read_text())

            # Only handle SpecimenScope for now
            if not isinstance(grader_input.scope, SpecimenScope):
                logger.warning(f"Skipping non-specimen scope in {run_dir}: {grader_input.scope.tag}")
                continue

            specimen_slug = grader_input.scope.specimen_slug

            # Load typed output to get grading results
            grader_output = GraderOutput.model_validate_json((run_dir / "output.json").read_text())

            # Get the critique that was graded (to access original issue details)
            if not isinstance(grader_input.critic_result, type(grader_input.critic_result)):
                # This handles both CriticSuccess and CriticFailure via duck typing
                # We need CriticSuccess to get the critique payload
                logger.warning(f"Skipping failed critic result in {run_dir}")
                continue

            # Access novel (unknown) issues from grading result
            # novel_critique_issues: dict[InputIssueID, str] (reasoning why it's novel)
            for input_id, _reasoning in grader_output.grade.novel_critique_issues.items():
                # Find the corresponding issue in the critique to get full details
                # critic_result is CriticOutput (discriminated union)
                # We need to check if it's a success to access the result
                if grader_input.critic_result.tag != "success":
                    continue

                critique = grader_input.critic_result.result

                # Find the issue by ID
                matching_issue = next((issue for issue in critique.issues if issue.id == str(input_id)), None)

                if not matching_issue:
                    logger.warning(f"Could not find issue {input_id} in critique for {run_dir}")
                    continue

                # Collect all files from all occurrences
                files: set[str] = set()
                for occ in matching_issue.occurrences:
                    files.update(str(f) for f in occ.files)

                issues.append(
                    UnknownIssue(
                        specimen=specimen_slug,
                        id=input_id,
                        should_flag=None,  # Unknown issues need human triage
                        rationale=matching_issue.rationale,
                        files=files,
                        run_path=run_dir,
                    )
                )

        except Exception as e:
            logger.warning(f"Failed to load unknowns from {run_dir}: {e}")
            continue

    return issues


async def cluster_unknowns_async(
    issues: list[UnknownIssue], *, model: str, out_root: Path, client: OpenAIModelProto
) -> Path:
    """Run the in-proc MCP clustering agent and write clusters.json under out_root.

    Returns the output directory path.
    """

    state = ClusterSubmitState()

    # Helper to compute unique key for clustering (internal to this function)
    def _issue_key(issue: UnknownIssue) -> str:
        return f"{issue.run_path.name}::{issue.id}"

    def _builder(s: NotifyingFastMCP) -> None:
        @s.tool()
        def submit_result(payload: ClusterSubmitPayload) -> str:
            # Validate coverage: every key appears in >=1 submitted cluster
            seen: set[str] = set()
            for c in payload.clusters:
                for it in c.issues:
                    seen.add(it)
            all_keys = {_issue_key(u) for u in issues}
            missing = sorted(all_keys - seen)
            if missing:
                raise ValueError(f"missing {len(missing)} issue(s) in clusters; first: {missing[:3]}")
            state.result = payload.clusters
            return "ok"

    comp = Compositor("compositor")
    srv = NotifyingFastMCP("cluster_submit", instructions="Cluster submit")
    _builder(srv)
    await comp.mount_inproc("cluster_submit", srv)
    system = (
        "You cluster semantically equivalent issues. You MUST call cluster_submit.submit_result exactly once with: "
        "[{name:string, issues:[string,...]}]."
    )
    # Serialize issues with key for LLM clustering (internal key, not exposed on model)
    # TODO: Improve serialization - avoid manual JSON wrangling, use proper Pydantic serialization helpers
    input_lines = "\n".join(
        json.dumps({**i.model_dump(exclude={"run_path", "specimen"}), "key": _issue_key(i)}, ensure_ascii=False)
        for i in issues
    )
    async with Client(comp) as mcp_client:

        def _ready_state() -> bool:
            return state.result is not None

        agent = await MiniCodex.create(
            model=model,
            mcp_client=mcp_client,
            system=system,
            client=client,
            handlers=[TranscriptHandler(dest_dir=out_root), GateUntil(_ready_state)],
            parallel_tool_calls=True,
        )
        user = "Cluster the following issues. Every uid must appear in >=1 cluster.\n\n" + input_lines
        await agent.run(user)
    if state.result is None:
        raise RuntimeError("cluster_submit.submit_result not called")
    (out_root / "clusters.json").write_text(
        json.dumps([c.model_dump() for c in state.result], indent=2), encoding="utf-8"
    )
    return out_root


def cluster_unknowns(*, model: str = "gpt-5", out_dir: Path | None = None, runs_dir: Path | None = None) -> Path:
    """Cluster unknowns per specimen in parallel using an LLM (one run per specimen).

    - Discovers grader runs and loads unknown issues from output.json files (using Pydantic)
    - Partitions unknowns by specimen and launches an in-proc MCP clustering agent per specimen concurrently
    - LLM input excludes specimen and run_path (implicitly scoped to the specimen)
    - Each specimen writes clusters.json under runs/cluster/<ts>/{specimen}/
    - Returns the root directory containing per-specimen outputs

    Args:
        model: LLM model to use for clustering
        out_dir: Optional output directory override
        runs_dir: Base runs directory (if None, uses pkg_dir() / "runs" - should be passed from caller)
    """
    # Compute runs directory once (caller should pass this, but allow fallback for backwards compat)
    # TODO: Remove fallback once all callers are updated to pass runs_dir explicitly
    if runs_dir is None:
        runs_dir = pkg_dir() / "runs"

    grader_run_dirs = discover_grader_runs(runs_dir)
    issues = load_unknowns(grader_run_dirs)
    if not issues:
        raise RuntimeError(f"no unknown issues found in grader runs under {runs_dir}/*/grader/*/*/")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if out_dir is not None:
        root: Path = Path(out_dir).expanduser().resolve()
    else:
        root = runs_dir / "cluster" / ts
    root.mkdir(parents=True, exist_ok=True)

    # Partition by specimen
    by_spec = {u.specimen: [u] for u in issues}

    # Construct a single typed client per invocation
    typed_client = build_client(model)

    async def _run_all() -> Path:
        tasks = []
        for spec, items in by_spec.items():
            out_spec = root / spec
            out_spec.mkdir(parents=True, exist_ok=True)
            tasks.append(cluster_unknowns_async(items, model=model, out_root=out_spec, client=typed_client))
        # Run in parallel; await all
        await asyncio.gather(*tasks)
        return root

    out_root_path: Path = asyncio.run(_run_all())
    return out_root_path

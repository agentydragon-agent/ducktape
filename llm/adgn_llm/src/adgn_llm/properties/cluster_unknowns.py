import asyncio
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import yaml
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.aggregating_handler import GateUntil
from adgn_llm.mini_codex.mcp_manager import McpManager
from adgn_llm.mini_codex.transcript_handler import TranscriptHandler
from adgn_llm.properties.prop_utils import pkg_dir
from mcp.server.fastmcp import FastMCP  # type: ignore
from openai import AsyncOpenAI
from pydantic import BaseModel, Field


class UnknownIssue(BaseModel):
    """Structured view of a single 'unknown' YAML emitted by prompt_optimize runs."""

    uid: str = Field(..., description="Unique id, prefixed with run/specimen to avoid collisions")
    specimen: str
    id: str
    should_flag: bool | None = None
    rationale: str
    files: list[str]
    yaml_path: str


def discover_unknown_yaml_paths(root: Path | None = None) -> list[Path]:
    """Find all runs/prompt_optimize/**/unknowns/*.yaml under package runs/.

    Returns newest-first (by path sort is fine; consumers don't assume order).
    """
    runs_root = (root or pkg_dir()) / "runs" / "prompt_optimize"
    return sorted(runs_root.rglob("*/unknowns/*.yaml"))


def load_unknowns(paths: Iterable[Path]) -> list[UnknownIssue]:
    """Load and normalize unknown YAML files into UnknownIssue models."""
    issues: list[UnknownIssue] = []
    for yp in paths:
        try:
            data = yaml.safe_load(yp.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        core = (data or {}).get("core") or {}
        occ = (data or {}).get("occurrence") or {}
        parts = yp.parts
        try:
            idx = parts.index("unknowns")
            specimen = parts[idx - 1]
            run_ts = parts[idx - 2]
        except Exception:
            specimen = "UNKNOWN"
            run_ts = ""
        iid = str(core.get("id") or "")
        files = list((occ.get("files") or {}).keys())
        uid = f"{run_ts}:{iid}"
        issues.append(
            UnknownIssue(
                uid=uid,
                specimen=specimen,
                id=iid,
                should_flag=core.get("should_flag"),
                rationale=str(core.get("rationale") or ""),
                files=files,
                yaml_path=str(yp),
            )
        )
    return issues


async def cluster_unknowns_async(issues: list[UnknownIssue], *, model: str, out_root: Path) -> Path:
    """Run the in-proc MCP clustering agent and write clusters.json under out_root.

    Returns the output directory path.
    """

    class ClusterSpec(BaseModel):
        name: str
        issues: list[str]

    class ClusterSubmitPayload(BaseModel):
        clusters: list[ClusterSpec]

    class ClusterSubmitState:
        def __init__(self) -> None:
            self.result: list[ClusterSpec] | None = None

    state = ClusterSubmitState()
    mcp = FastMCP(
        "cluster_submit",
        instructions=(
            "Submit clusters via submit_result once and only once. The payload must be "
            "a JSON array of objects: [{name: string, issues: [string, ...]}]."
        ),
    )

    @mcp.tool()
    def submit_result(payload: ClusterSubmitPayload) -> str:  # type: ignore[no-redef]
        # Validate coverage: every uid appears in >=1 submitted cluster
        seen: set[str] = set()
        for c in payload.clusters:
            for it in c.issues:
                seen.add(it)
        all_uids = {u.uid for u in issues}
        missing = sorted(all_uids - seen)
        if missing:
            raise ValueError(f"missing {len(missing)} issue(s) in clusters; first: {missing[:3]}")
        state.result = payload.clusters
        return "ok"

    specs = {"cluster_submit": make_inproc_slot_spec(mcp)}

    async with McpManager(specs) as mcp_mgr:
        system = (
            "You cluster semantically equivalent issues. You MUST call cluster_submit.submit_result exactly once with: "
            "[{name:string, issues:[string,...]}]. Do not emit any other final text."
        )
        input_lines = "\n".join(
            json.dumps(i.model_dump(exclude={"yaml_path", "specimen"}), ensure_ascii=False) for i in issues
        )
        agent = await MiniCodex.create(
            model=model,
            mcp=mcp_mgr,
            system=system,
            client=AsyncOpenAI(),
            handlers=[TranscriptHandler(dest_dir=out_root), GateUntil(lambda: state.result is not None)],
            parallel_tool_calls=True,
        )
        user = (
            "Cluster the following issues (one JSON per line). Every uid must appear in >=1 cluster.\n\n" + input_lines
        )
        await agent.run(user)
        if state.result is None:
            raise RuntimeError("cluster_submit.submit_result not called")
        (out_root / "clusters.json").write_text(
            json.dumps([c.model_dump() for c in state.result], indent=2),
            encoding="utf-8",
        )
        return out_root


def cluster_unknowns(
    *,
    model: str = "gpt-5",
    out_dir: Optional[Path] = None,
    runs_root: Optional[Path] = None,
) -> Path:
    """Cluster unknowns per specimen in parallel using an LLM (one run per specimen).

    - Partitions unknowns by specimen and launches an in-proc MCP clustering agent per specimen concurrently
    - LLM input excludes specimen and yaml_path (implicitly scoped to the specimen)
    - Each specimen writes clusters.json under runs/cluster_unknowns/<ts>/<specimen>/
    - Returns the root directory containing per-specimen outputs
    """
    paths = discover_unknown_yaml_paths(runs_root)
    issues = load_unknowns(paths)
    if not issues:
        raise RuntimeError("no unknown YAMLs found under runs/prompt_optimize/**/unknowns/")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = (
        Path(out_dir).expanduser().resolve() if out_dir is not None else (pkg_dir() / "runs" / "cluster_unknowns" / ts)
    )
    root.mkdir(parents=True, exist_ok=True)

    # Partition by specimen
    by_spec: dict[str, list[UnknownIssue]] = defaultdict(list)
    for u in issues:
        by_spec[u.specimen].append(u)

    async def _run_all() -> Path:
        tasks = []
        for spec, items in by_spec.items():
            out_spec = root / spec
            out_spec.mkdir(parents=True, exist_ok=True)
            tasks.append(cluster_unknowns_async(items, model=model, out_root=out_spec))
        # Run in parallel; await all
        await asyncio.gather(*tasks)
        return root

    return asyncio.run(_run_all())

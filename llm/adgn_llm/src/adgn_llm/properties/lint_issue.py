from __future__ import annotations

import json
import shutil
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from adgn_llm.properties.prop_utils import properties_root, find_property_files
from adgn_llm.properties.specimen_utils import load_single_issue
from openai.types.responses import ResponseFunctionToolCall

from adgn_llm.mcp.docker_exec.server import make_container_exec_mcp
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.mcp_manager import McpManager, build_mcp_function
from adgn_llm.mini_codex.loop_control import (
    LoopController,
    BaseLoopController,
    Continue,
    Auto,
    SyntheticAction,
)
from adgn_llm.mcp.docker_exec.server import (
    SERVER_NAME as DOCKER_SERVER_NAME,
    TOOL_EXEC_NAME as DOCKER_EXEC_TOOL_NAME,
)
from adgn_llm.mini_codex.event_renderer import (
    ConsoleEventRenderer,
    PrettyPrintController,
)
from .specimen_utils import (
    ensure_archive_for_specimen_slug,
    Occurrence,
)

DOCKER_IMAGE = "python:3.12-slim"


@dataclass
class LintConfig:
    specimen: str
    issue_id: str
    model: str = "gpt-5"
    dry_run: bool = False


def _build_prompt(
    issue: Any, property_md_files: list[Path], occurrence: Any | None = None
) -> str:
    # Do not include specimen slug or issue id. Include only issue fields and property definitions.
    # The agent will read code from /workspace via MCP.
    issue_dict = issue.model_dump(exclude_none=True)
    issue_dict.pop("id", None)
    if occurrence is not None:
        try:
            issue_dict["instances"] = [occurrence.model_dump(exclude_none=True)]
        except Exception:
            issue_dict["instances"] = [occurrence]
    issue_json = json.dumps(issue_dict, ensure_ascii=False)

    md_blocks: list[str] = []
    props_root = properties_root()
    for md in property_md_files:
        rel = md.relative_to(props_root)
        md_blocks.append(
            f'<file path=":/{rel.as_posix()}">\n{md.read_text(encoding="utf-8")}\n</file>',
        )

    tool_name = build_mcp_function(DOCKER_SERVER_NAME, DOCKER_EXEC_TOOL_NAME)

    lines = [
        "Lint the following single issue strictly against the provided property definition files.",
        f"Use the function {tool_name} to read files under /workspace (read-only).",
        "Do not modify code. Judge only by the definitions as written.",
        "",
        "Issue (JSON):",
        issue_json,
        "",
        "Property definitions:",
        *md_blocks,
        "",
        "Requirements:",
        (
            "- First, call mcp__resources__read (server='docker', uri='resource://container.info') to discover working_dir and volumes; then use "
            f"{tool_name} to fetch and quote the exact anchored lines (and a few lines of context if helpful)."
        ),
        "- For each property listed, verify the anchored code truly violates the definition.",
        "- If an anchor range misses, suggest minimal corrected 1-based ranges (file and [start,end?]).",
        "- If any listed property does not apply, explain briefly why.",
        "- Output freeform text; conclude with a final line: PASS or ERROR.",
    ]
    return "\n".join(lines).strip()


async def _run_agent(
    prompt: str,
    slots: dict[str, Any],
    model: str,
    client: AsyncOpenAI,
    controller: LoopController,
) -> str:
    async with McpManager(slots) as mcp:
        agent = await MiniCodex.create(
            model=model,
            mcp=mcp,
            system="You are a code agent. Be concise.",
            client=client,
        )
        result = await agent.run(prompt, controller=controller)
        return result.text or ""

BIG_THRESHOLD = 20480


def _make_bootstrap_controller(occ: Occurrence, content_root: Path) -> LoopController:
    # Deterministic bootstrap with serial steps:
    # Turn 1: read docker container info resource
    # Turn 2: ls -la on all parent directories in one command
    # Turn 3: per-file content (cat for small); if any file >=20kB, abort bootstrap before turn 3

    files = list((occ.files or {}).keys())
    dirs = sorted({str(Path(p).parent) for p in files})

    # Determine sizes using local filesystem view of mounted content_root; fatal on missing/permission issues
    sizes: dict[str, int] = {}
    for p in files:
        hp = (content_root / p).resolve()
        st = (
            hp.stat()
        )  # Let FileNotFoundError/PermissionError crash: malformed specimen
        if not hp.is_file():
            raise SystemExit(f"Expected a regular file for occurrence path: {hp}")
        sizes[p] = int(st.st_size)
    big_detected = any(size >= BIG_THRESHOLD for size in sizes.values())

    # Pre-build calls per step
    step1 = [
        ResponseFunctionToolCall(
            type="function_call",
            name="mcp__resources__read",
            call_id="bootstrap:res",
            arguments=json.dumps(
                {
                    "server": "docker",
                    "uri": "resource://container.info",
                    "start_offset": 0,
                    "max_bytes": 65536,
                }
            ),
        )
    ]

    if dirs:
        # Build argv without shell: ls -la dir1 dir2 ...
        step2 = [
            ResponseFunctionToolCall(
                type="function_call",
                name=build_mcp_function(DOCKER_SERVER_NAME, DOCKER_EXEC_TOOL_NAME),
                call_id="bootstrap:ls",
                arguments=json.dumps({"cmd": ["ls", "-la"] + ["/workspace/" + d for d in dirs]}),
            )
        ]
    else:
        step2 = []

    # Build per-file content commands (only when all are small)
    def _content_calls() -> list[ResponseFunctionToolCall]:
        out: list[ResponseFunctionToolCall] = []
        for p in files:
            if sizes[p] > BIG_THRESHOLD:
                # unreachable when big_detected is False; defer to model (no synthetic call)
                continue
            out.append(
                ResponseFunctionToolCall(
                    type="function_call",
                    name=build_mcp_function(DOCKER_SERVER_NAME, DOCKER_EXEC_TOOL_NAME),
                    call_id=f"bootstrap:show:{len(out) + 1}",
                    arguments=json.dumps({"cmd": ["nl", "-ba", "-w1", "-s", " ", f"/workspace/{p}"]}),
                )
            )
        return out

    class _BootstrapCtrl(BaseLoopController):
        def __init__(self) -> None:
            self._step = 0

        def on_before_sample(self):
            self._step += 1
            if self._step == 1:
                return SyntheticAction(outputs=step1)
            if self._step == 2 and step2:
                return SyntheticAction(outputs=step2)
            if self._step == 3 and files and not big_detected:
                return SyntheticAction(outputs=_content_calls())
            return Continue(Auto())

    return _BootstrapCtrl()


def _extract_tar_gz_to(archive: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    dst.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(dst)


async def run_specimen_lint_issue_async(
    specimen: str,
    issue_id: str,
    *,
    model: str = "gpt-5",
    dry_run: bool = False,
    gitconfig: str | None = None,
    occurrence_index: int,
    client: AsyncOpenAI,
) -> int:
    sp, root, issue = load_single_issue(specimen, issue_id, gitconfig)

    # Require a single occurrence; do not run on the full issue or mutate the Issue
    if occurrence_index < 0 or occurrence_index >= len(issue.instances):
        raise SystemExit(
            f"occurrence_index out of range: {occurrence_index} (instances={len(issue.instances)})",
        )
    occ = issue.instances[occurrence_index]

    # Always mount from under $HOME to avoid Docker volume restrictions on /var/folders
    ts = int(time.time())
    name = f"lint_{ts}"
    mount_root = Path.home() / ".cache" / "adgn-llm" / "workspaces" / f"{specimen}_{name}"
    mount_root.mkdir(parents=True, exist_ok=True)

    if dry_run:
        props = find_property_files([str(p) for p in issue.properties])
        prompt = _build_prompt(issue, props, occurrence=occ)
        tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
        tmpdir.mkdir(parents=True, exist_ok=True)
        outfile = tmpdir / f"lint_issue_{issue_id}_{ts}.md"
        outfile.write_text(prompt, encoding="utf-8")
        # Determine content root deterministically for dry-run
        entries = [p for p in mount_root.iterdir() if p.is_dir()]
        if len(entries) != 1:
            raise SystemExit(
                f"Unexpected archive layout under {mount_root}; expected a single top-level directory",
            )
        content_root = entries[0]
        print(
            (
                f"[dry-run] docker run -d --rm -v '{content_root}:/workspace:ro' -w /workspace "
                f"--name lint_{ts} {DOCKER_IMAGE} sleep infinity"
            ),
        )
        print(f"[dry-run] Saved prompt: {outfile}")
        return 0

    try:
        # Prepare mount directory under $HOME from cached archive; hard-fail if cache missing
        if mount_root.exists():
            shutil.rmtree(mount_root, ignore_errors=True)
        archive = ensure_archive_for_specimen_slug(
            sp.manifest, sp.manifest_path, Path(gitconfig) if gitconfig else None
        )
        _extract_tar_gz_to(archive, mount_root)

        # Determine content root: expect exactly one top-level directory after extraction
        entries = [p for p in mount_root.iterdir() if p.is_dir()]
        if len(entries) != 1:
            raise SystemExit(
                f"Unexpected archive layout under {mount_root}; expected a single top-level directory",
            )
        content_root = entries[0]

        # Build in-process FastMCP server spec for docker exec (single-process for easier debug)
        spec = make_inproc_slot_spec(
            make_container_exec_mcp(
                image=DOCKER_IMAGE,
                working_dir="/workspace",
                volumes={str(content_root): {"bind": "/workspace", "mode": "ro"}},
                describe=True,
            )
        )
        specs = {"docker": spec}
        props = find_property_files([str(p) for p in issue.properties])
        prompt = _build_prompt(issue, props, occurrence=occ)
        base_ctrl = _make_bootstrap_controller(occ, content_root)
        ctrl = PrettyPrintController(
            base_ctrl, renderer=ConsoleEventRenderer(show_text=False)
        )
        text = await _run_agent(prompt, specs, model, client, controller=ctrl)
        # Print the exact occurrence representation as fed to the model
        issue_dict = issue.model_dump(exclude_none=True)
        issue_dict.pop("id", None)
        try:
            occ_dict = occ.model_dump(exclude_none=True)
        except Exception:
            occ_dict = occ  # fallback if already a dict-like
        issue_dict["instances"] = [occ_dict]
        issue_json = json.dumps(issue_dict, ensure_ascii=False)
        print("Issue (JSON):")
        print(issue_json)
        print()
        print(text)
        # Heuristic: final line contains PASS → success
        tail = (text.splitlines() or [""])[-1].strip().upper()
        return 0 if tail == "PASS" else 2
    finally:
        # Cleanup copied workspace
        if mount_root.exists():
            shutil.rmtree(mount_root, ignore_errors=True)

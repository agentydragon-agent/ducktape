from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tarfile
import tempfile
import time
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from adgn_llm.mcp.docker_exec.server import make_container_exec_mcp
from adgn_llm.mcp.inproc_utils import make_inproc_slot_spec
from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.mcp_manager import McpManager

from .specimen_utils import Specimen, ensure_archive_for_specimen_slug

DOCKER_IMAGE = "python:3.12-slim"


@dataclass
class LintConfig:
    specimen: str
    issue_id: str
    model: str = "gpt-5"
    dry_run: bool = False


def _load_single_issue(specimen: str, issue_id: str, gitconfig: str | None) -> tuple[Specimen, Path, Any]:
    sp = Specimen.load(specimen)
    # Ensure we have a fresh, private checkout/copy of the specimen source.
    # TODO(mpokorny): Plumb a cleaner auth mechanism; for now auto-read a local gitconfig if present.
    if gitconfig is None:
        try:
            cfg = Path(files("adgn_llm").joinpath("properties", "gitconfig.local"))
            if cfg.exists():
                gitconfig = str(cfg)
        except Exception:
            pass
    gc_path = Path(gitconfig).expanduser().resolve() if gitconfig else None
    root = sp.obtain_code(gitconfig=gc_path)
    issue = sp.get_issue(issue_id)
    if not issue.should_flag:
        raise SystemExit(
            f"Issue should_flag=false is not supported by linter: {issue_id}",
        )
    return sp, root, issue


def _find_property_files(property_ids: list[str]) -> list[Path]:
    props_root = Path(files("adgn_llm").joinpath("properties"))
    defs_dir = props_root / "definitions"
    wanted = set(property_ids)
    found: list[Path] = []
    if not defs_dir.exists():
        return found
    # Search by filename stem
    for md in defs_dir.rglob("*.md"):
        if md.stem in wanted:
            found.append(md)
    return sorted(found, key=lambda p: p.as_posix())


def _build_prompt(issue: Any, property_md_files: list[Path], occurrence: Any | None = None) -> str:
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
    props_root = Path(files("adgn_llm").joinpath("properties"))
    for md in property_md_files:
        rel = md.relative_to(props_root)
        md_blocks.append(
            f'<file path=":/{rel.as_posix()}">\n{md.read_text(encoding="utf-8")}\n</file>',
        )

    lines = [
        "Lint the following single issue strictly against the provided property definition files.",
        "Use the function mcp__docker__exec to read files under /workspace (read-only).",
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
            "- First, call mcp__docker__session_info to discover working_dir and volumes; then use "
            "mcp__docker__exec to fetch and quote the exact anchored lines (and a few lines of context if helpful)."
        ),
        "- For each property listed, verify the anchored code truly violates the definition.",
        "- If an anchor range misses, suggest minimal corrected 1-based ranges (file and [start,end?]).",
        "- If any listed property does not apply, explain briefly why.",
        "- Output freeform text; conclude with a final line: PASS or ERROR.",
    ]
    return "\n".join(lines).strip()


async def _run_agent(
    prompt: str,
    slots: dict[str, ServerSlot],
    model: str,
    client: AsyncOpenAI,
) -> str:
    async with McpManager(slots) as mcp:
        agent = await MiniCodex.create(
            model=model,
            mcp=mcp,
            system="You are a code agent. Be concise.",
            client=client,
        )
        result = await agent.run(prompt)
        return result.text.strip() if result.text else ""


def _docker_run_detached(root: Path, name: str) -> str:
    argv = [
        "docker",
        "run",
        "-d",
        "--rm",
        "-v",
        f"{root!s}:/workspace:ro",
        "-w",
        "/workspace",
        "--name",
        name,
        DOCKER_IMAGE,
        "sleep",
        "infinity",
    ]
    cp = subprocess.run(argv, check=False, text=True, capture_output=True)
    if cp.returncode != 0:
        raise SystemExit(f"docker run failed: {cp.stderr.strip()}")
    return cp.stdout.strip()


def _docker_rm_force(name_or_id: str) -> None:
    subprocess.run(
        ["docker", "rm", "-f", name_or_id],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _extract_tar_gz_to(archive: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    dst.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(dst)


def run_specimen_lint_issue(
    specimen: str,
    issue_id: str,
    *,
    model: str = "gpt-5",
    dry_run: bool = False,
    gitconfig: str | None = None,
    occurrence_index: int,
    client: AsyncOpenAI,
) -> int:
    sp, root, issue = _load_single_issue(specimen, issue_id, gitconfig)

    # Require a single occurrence; do not run on the full issue or mutate the Issue
    if occurrence_index < 0 or occurrence_index >= len(issue.instances):
        raise SystemExit(
            f"occurrence_index out of range: {occurrence_index} (instances={len(issue.instances)})",
        )
    occ = issue.instances[occurrence_index]

    # Always mount from under $HOME to avoid Docker volume restrictions on /var/folders
    ts = int(time.time())
    name = f"lint_{ts}"
    mount_base = Path.home() / ".cache" / "adgn-llm" / "workspaces"
    mount_base.mkdir(parents=True, exist_ok=True)
    mount_root = mount_base / f"{specimen}_{name}"

    if dry_run:
        props = _find_property_files([str(p) for p in issue.properties])
        prompt = _build_prompt(issue, props, occurrence=occ)
        tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
        tmpdir.mkdir(parents=True, exist_ok=True)
        outfile = tmpdir / f"lint_issue_{issue_id}_{ts}.md"
        outfile.write_text(prompt, encoding="utf-8")
        print(
            (
                f"[dry-run] docker run -d --rm -v '{mount_root}:/workspace:ro' -w /workspace "
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

        # Build in-process FastMCP server spec for docker exec (single-process for easier debug)
        spec = make_inproc_slot_spec(
            make_container_exec_mcp(
                image=DOCKER_IMAGE,
                working_dir="/workspace",
                volumes={str(mount_root): {"bind": "/workspace", "mode": "ro"}},
                describe=True,
            )
        )
        specs = {"docker": spec}
        props = _find_property_files([str(p) for p in issue.properties])
        prompt = _build_prompt(issue, props, occurrence=occ)
        text = asyncio.run(_run_agent(prompt, specs, model, client))
        print(text)
        # Heuristic: final line contains PASS → success
        tail = (text.splitlines() or [""])[-1].strip().upper()
        return 0 if tail == "PASS" else 2
    finally:
        # Cleanup copied workspace
        if mount_root.exists():
            shutil.rmtree(mount_root, ignore_errors=True)

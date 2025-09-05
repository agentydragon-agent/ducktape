from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

import openai
from adgn_llm.mini_codex.agent import MiniCodex

from .specimen_utils import Specimen

DOCKER_IMAGE = "python:3.12-slim"


@dataclass
class LintConfig:
    specimen: str
    issue_id: str
    model: str = "gpt-5"
    dry_run: bool = False


def _load_single_issue(specimen: str, issue_id: str) -> tuple[Path, Any]:
    sp = Specimen.load(specimen)
    issue = sp.get_issue(issue_id)
    if not issue.should_flag:
        raise SystemExit(
            f"Issue should_flag=false is not supported by linter: {issue_id}",
        )
    return sp.root, issue


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


def _build_prompt(issue: Any, property_md_files: list[Path]) -> str:
    # Do not include specimen slug or issue id. Include only issue fields and property definitions.
    # The agent will read code from /workspace via MCP.
    issue_json = issue.model_dump_json(exclude_none=True, exclude={"id": True})

    md_blocks: list[str] = []
    props_root = Path(files("adgn_llm").joinpath("properties"))
    for md in property_md_files:
        rel = md.relative_to(props_root)
        md_blocks.append(
            f'<file path=":/{rel.as_posix()}">\n{md.read_text(encoding="utf-8")}\n</file>',
        )

    lines = [
        "Lint the following single issue strictly against the provided property definition files.",
        "Use the function mcp__docker__docker_exec to read files under /workspace (read-only).",
        "Do not modify code. Judge only by the definitions as written.",
        "",
        "Issue (JSON):",
        issue_json,
        "",
        "Property definitions:",
        *md_blocks,
        "",
        "Requirements:",
        "- First, use mcp__docker__docker_exec to fetch and quote the exact anchored lines (and a few lines of context if helpful).",
        "- For each property listed, verify the anchored code truly violates the definition.",
        "- If an anchor range misses, suggest minimal corrected 1-based ranges (file and [start,end?]).",
        "- If any listed property does not apply, explain briefly why.",
        "- Output freeform text; conclude with a final line: PASS or ERROR.",
    ]
    return "\n".join(lines).strip()


async def _run_agent(prompt: str, tools: dict[str, Any], model: str) -> str:
    client = openai.OpenAI()
    agent = await MiniCodex.start(
        model=model,
        tools=tools,
        system="You are a code agent. Be concise.",
        client=client,
    )
    try:
        result = await agent.run(prompt)
        return result.text.strip() if result.text else ""
    finally:
        await agent.close()


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


def run_specimen_lint_issue(
    specimen: str, issue_id: str, *, model: str = "gpt-5", dry_run: bool = False,
) -> int:
    root, issue = _load_single_issue(specimen, issue_id)

    if dry_run:
        props = _find_property_files([str(p) for p in issue.properties])
        prompt = _build_prompt(issue, props)
        tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
        tmpdir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        outfile = tmpdir / f"lint_issue_{issue_id}_{ts}.md"
        outfile.write_text(prompt, encoding="utf-8")
        print(
            f"[dry-run] docker run -d --rm -v '{root}:/workspace:ro' -w /workspace --name lint_{ts} {DOCKER_IMAGE} sleep infinity",
        )
        print(f"[dry-run] Saved prompt: {outfile}")
        return 0

    name = f"lint_{int(time.time())}"
    cid = None
    try:
        cid = _docker_run_detached(root, name)
        # Build MCP tool map for docker_exec server
        tools = {
            "docker": {
                "command": sys.executable,
                "args": [
                    "-m",
                    "adgn_llm.mcp.docker_exec.server",
                ],
                "env": {
                    "DOCKER_CONTAINER": cid,
                    "DOCKER_DEFAULT_CWD": "/workspace",
                },
            },
        }
        props = _find_property_files([str(p) for p in issue.properties])
        prompt = _build_prompt(issue, props)
        text = asyncio.run(_run_agent(prompt, tools, model))
        print(text)
        # Heuristic: final line contains PASS → success
        tail = (text.splitlines() or [""])[-1].strip().upper()
        return 0 if tail == "PASS" else 2
    finally:
        if cid:
            _docker_rm_force(cid)
        else:
            _docker_rm_force(name)

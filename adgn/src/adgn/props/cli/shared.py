"""Shared CLI utilities for adgn-properties commands."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
import time

from fastmcp.client import Client
from fastmcp.server import FastMCP
import tiktoken

from adgn.agent.agent import Agent, TranscriptItem
from adgn.agent.display import OneLineProgressHandler
from adgn.agent.loop_control import RequireAnyTool
from adgn.agent.transcript_handler import TranscriptHandler
from adgn.mcp.compositor.server import Compositor
from adgn.openai_utils.model import OpenAIModelProto, SystemMessage, UserMessage
from adgn.props.docker_env import properties_docker_spec
from adgn.props.runs_context import format_timestamp_session


@dataclass
class AgentResult:
    final_text: str
    transcript: list[TranscriptItem]


async def run_prompt_async(
    prompt: str,
    server_factories: Mapping[str, Callable[..., FastMCP]],
    client: OpenAIModelProto,
    system_prompt: str = "You are a code agent. Be concise.",
) -> AgentResult:
    """Run the prompt using Agent + MCP specs and return an AgentResult.

    This is the low-level primitive for running prompts through MCP-backed Agent.
    Uses quiet single-line progress handler and per-run transcript directory.
    """
    transcript: list[TranscriptItem] = []
    # Use Compositor as async context manager to ensure cleanup
    async with Compositor() as comp:
        for name, factory in server_factories.items():
            server = factory()
            await comp.mount_inproc(name, server)
        # Quiet, single-line progress by default (DisplayEventsHandler available for verbose UI)
        # Per-run transcript directory (logs/ for ad-hoc debugging)
        run_dir = Path.cwd() / "logs" / "agent" / "agent_runner"
        run_dir = run_dir / f"run_{int(time.time())}_{os.getpid()}"
        run_dir.mkdir(parents=True, exist_ok=True)
        async with Client(comp) as mcp_client:
            agent = await Agent.create(
                mcp_client=mcp_client,
                client=client,
                handlers=[OneLineProgressHandler(), TranscriptHandler(events_path=run_dir / "events.jsonl")],
                tool_policy=RequireAnyTool(),
                dynamic_instructions=comp.render_agent_dynamic_instructions,
            )
            agent.insert_messages([SystemMessage.text(system_prompt), UserMessage.text(prompt)])
            res_any = await agent.run()
    # Compositor.__aexit__ unmounts all non-pinned servers and cleans up containers here

    return AgentResult(final_text=res_any.text, transcript=transcript)


@dataclass(frozen=True)
class BuildOptions:
    sandbox: str
    skip_git_repo_check: bool
    full_auto: bool
    extra_configs: list[str] | None = None


def save_prompt_to_tmp(stem: str, text: str) -> Path:
    """Save prompt text under the system temp dir and print a short summary.

    File name: <stem>_<ts>.md. Prints an approximate token count using tiktoken.
    """
    tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
    tmpdir.mkdir(parents=True, exist_ok=True)
    ts = format_timestamp_session()
    outfile = tmpdir / f"{stem}_{ts}.md"
    outfile.write_text(text, encoding="utf-8")
    tokens = len(tiktoken.get_encoding("cl100k_base").encode(text))
    print(f"Saved prompt: {outfile} (approx tokens: {tokens})")
    return outfile


def build_cmd(model: str, workdir: Path, opts: BuildOptions) -> list[str]:
    cmd: list[str] = ["codex", "exec", "--model", model, "--sandbox", opts.sandbox, "-C", str(workdir)]
    if opts.extra_configs:
        for c in opts.extra_configs:
            cmd.extend(["-c", c])
    if opts.full_auto:
        cmd.append("--full-auto")
    if opts.skip_git_repo_check:
        cmd.append("--skip-git-repo-check")
    return cmd


async def run_check_minicodex_async(
    workdir: Path,
    prompt: str,
    *,
    model: str,
    output_final_message: Path | None,
    final_only: bool,
    client: OpenAIModelProto,
) -> int:
    wiring = properties_docker_spec(workdir, mount_properties=True)
    server_factories = {wiring.server_name: wiring.server_factory}
    res = await run_prompt_async(prompt, server_factories, client=client)
    if output_final_message:
        Path(output_final_message).write_text(res.final_text, encoding="utf-8")
    if not final_only and res.final_text:
        print(res.final_text)
    return 0

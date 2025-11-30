from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
from uuid import UUID

import tiktoken

from adgn.openai_utils.model import OpenAIModelProto
from adgn.props.agent_runner import run_prompt_async
from adgn.props.db import get_session
from adgn.props.db.models import Prompt
from adgn.props.docker_env import properties_docker_spec
from adgn.props.runs_context import format_timestamp_session


@dataclass(frozen=True)
class BuildOptions:
    sandbox: str
    skip_git_repo_check: bool
    full_auto: bool
    extra_configs: list[str] | None = None


def hash_and_upsert_prompt(prompt_text: str, prompt_optimization_run_id: UUID | None = None) -> str:
    """Compute SHA-256 hash of prompt text and upsert to database.

    Args:
        prompt_text: The prompt content to hash and store
        prompt_optimization_run_id: Optional ID of the optimization run that generated this prompt

    Returns:
        The computed SHA-256 hash.
    """
    prompt_sha256 = hashlib.sha256(prompt_text.encode()).hexdigest()
    with get_session() as session:
        prompt_obj = Prompt(
            prompt_sha256=prompt_sha256, prompt_text=prompt_text, prompt_optimization_run_id=prompt_optimization_run_id
        )
        session.merge(prompt_obj)
        session.flush()
    return prompt_sha256


def detect_tools() -> list[str]:
    tools = [
        ("ruff", "ruff"),
        ("mypy", "mypy"),
        ("pyright", "pyright"),
        ("vulture", "vulture"),
        ("bandit", "bandit"),
        ("pip-audit", "pip-audit"),
        ("safety", "safety"),
        ("codespell", "codespell"),
        ("pyupgrade", "pyupgrade"),
        ("refurb", "refurb"),
        ("flynt", "flynt"),
        ("pydocstyle", "pydocstyle"),
        ("interrogate", "interrogate"),
        ("import-linter", "lint-imports"),
        ("semgrep", "semgrep"),
        ("radon", "radon"),
        ("xenon", "xenon"),
        ("pylint", "pylint"),
        ("lizard", "lizard"),
        ("coverage", "coverage"),
        ("diff-cover", "diff-cover"),
        ("jscpd", "jscpd"),
    ]
    available: list[str] = []
    for name, exe in tools:
        if shutil.which(exe):
            available.append(name)
    if "jscpd" not in available and shutil.which("npx"):
        cp = subprocess.run(
            ["npx", "--yes", "--no-install", "jscpd", "--version"], check=False, text=True, capture_output=True
        )
        if cp.returncode == 0:
            available.append("jscpd(npx)")
    return available


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
    res = await run_prompt_async(prompt, model, server_factories, client=client)
    if output_final_message:
        Path(output_final_message).write_text(res.final_text, encoding="utf-8")
    if not final_only and res.final_text:
        print(res.final_text)
    return 0

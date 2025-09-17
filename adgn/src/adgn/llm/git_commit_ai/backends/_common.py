from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging
import os
import sys

from git import Repo

from ..core import (
    _build_ai_context,
    _extract_message_from_text,
    build_prompt as _build_prompt_claude,
)


@dataclass
class ExecResult:
    returncode: int
    stdout: str
    stderr: str


async def run_subprocess(
    cmd: list[str],
    *,
    deadline: timedelta | None,
    debug: bool,
    logger: logging.Logger,
) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        if deadline is None:
            stdout, stderr = await proc.communicate()
        else:
            async with asyncio.timeout(deadline.total_seconds()):
                stdout, stderr = await proc.communicate()
    except TimeoutError:
        proc.terminate()
        await proc.wait()
        secs_str = (
            "infinite" if deadline is None else str(int(deadline.total_seconds()))
        )
        print(f"# Error: command timed out after {secs_str} seconds", file=sys.stderr)
        raise
    return proc.returncode or 0, stdout or b"", stderr or b""


def truncate_prompt(prompt: str) -> str:
    max_chars = int(os.environ.get("GIT_AI_MAX_PROMPT", "20000"))
    if len(prompt) >= max_chars:
        prompt = (
            prompt[: max(0, max_chars - 100)] + "\n\n[TRUNCATED - prompt was too long]"
        )
    return prompt


def build_prompt_for_claude(
    repo: Repo,
    diff: str,
    passthru: list[str],
    previous_message: str | None,
) -> str:
    prompt = _build_prompt_claude(repo, diff, passthru, previous_message)
    return truncate_prompt(prompt)


def build_prompt_for_codex(
    repo: Repo,
    include_all: bool,
    previous_message: str | None,
) -> str:
    context = _build_ai_context(repo, include_all)
    if previous_message:
        return (
            "You are an expert engineer updating a Git commit message for an amended commit.\n"
            f"Previous commit message:\n{previous_message}\n\n"
            "Requirements:\n"
            "- Review the provided repository context and update the message to reflect all changes.\n"
            "- Write a concise, imperative-mood subject; if helpful, add a short bullet list body.\n"
            "- Output ONLY the message between <message> and </message> tags. No extra text.\n\n"
            f"Context:\n{context}\n"
        )
    return (
        "You are an expert engineer writing a Git commit message for the current changes.\n"
        "Requirements:\n"
        "- Review the provided repository context. If more context is needed, you may query the repository as needed.\n"
        "- Write a concise, imperative-mood subject; if helpful, add a short bullet list body.\n"
        "- Output ONLY the message between <message> and </message> tags. No extra text.\n\n"
        f"Context:\n{context}\n"
    )


def extract_message(text: str) -> str:
    return _extract_message_from_text(text)

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Optional
import sys

from git import Repo

from ..core import _build_ai_context, _extract_message_from_text


class CodexAI:
    """AI provider using `codex exec` to draft commit messages.

    Caching is handled by the caller before invoking this provider.
    """

    def __init__(
        self,
        repo: Repo,
        debug: bool = False,
        codex_bin: Optional[str] = None,
        timeout: Optional[timedelta] = None,
        previous_message: Optional[str] = None,
    ):
        self.repo = repo
        self.debug = debug
        self.codex_bin: str = codex_bin or os.environ.get("CODEX_BIN") or "codex"
        self.timeout = timeout
        self.previous_message = previous_message
        self.logger = logging.getLogger(__name__)

    async def generate(self, include_all: bool, model: str) -> str:
        """Run codex in read-only sandbox at repo root and return the commit message."""
        last_msg_path = Path(self.repo.git_dir) / "codex_last_message.txt"

        # Build prompt - let the agent inspect the repo itself
        context = _build_ai_context(self.repo, include_all)
        if self.previous_message:  # amending
            prompt = (
                "You are an expert engineer updating a Git commit message for an amended commit.\n"
                f"Previous commit message:\n{self.previous_message}\n\n"
                "Requirements:\n"
                "- Review the provided repository context and update the message to reflect all changes.\n"
                "- Write a concise, imperative-mood subject; if helpful, add a short bullet list body.\n"
                "- Output ONLY the message between <message> and </message> tags. No extra text.\n\n"
                f"Context:\n{context}\n"
            )
        else:
            prompt = (
                "You are an expert engineer writing a Git commit message for the current changes.\n"
                "Requirements:\n"
                "- Review the provided repository context. If more context is needed, you may query the repository as needed.\n"
                "- Write a concise, imperative-mood subject; if helpful, add a short bullet list body.\n"
                "- Output ONLY the message between <message> and </message> tags. No extra text.\n\n"
                f"Context:\n{context}\n"
            )

        wd = Path(self.repo.working_tree_dir) if self.repo.working_tree_dir else Path(self.repo.git_dir)
        cmd = [
            self.codex_bin,
            "exec",
            "--sandbox",
            "read-only",
            "-C",
            str(wd),
            "--output-last-message",
            str(last_msg_path),
        ]
        if model:
            cmd += ["-m", str(model)]
        cmd.append(str(prompt))

        if self.debug:
            shell_cmd = subprocess.list2cmdline([str(x) for x in cmd])
            self.logger.debug("Codex command:\n%s", shell_cmd)
            self.logger.debug("Codex prompt:\n%s", prompt)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            if self.timeout is None:
                stdout, stderr = await proc.communicate()
            else:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout.total_seconds())
        except TimeoutError:
            proc.terminate()
            await proc.wait()
            secs_str = "infinite" if self.timeout is None else str(int(self.timeout.total_seconds()))
            print(
                f"# Error: codex exec timed out after {secs_str} seconds",
                file=sys.stderr,
            )
            raise

        if self.debug:
            if stdout:
                self.logger.debug("Codex stdout:\n%s", stdout.decode(errors="replace"))
            if stderr:
                self.logger.debug("Codex stderr:\n%s", stderr.decode(errors="replace"))

        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode or 1, cmd, (stderr or b"").decode())

        try:
            raw_last = last_msg_path.read_text()
        except Exception as e:
            raise RuntimeError(f"codex exec did not produce a last message file: {e}")

        return _extract_message_from_text(raw_last)

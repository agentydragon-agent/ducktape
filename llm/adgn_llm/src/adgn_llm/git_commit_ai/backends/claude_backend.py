from __future__ import annotations

import asyncio
import logging
import os
import sys
import subprocess
from datetime import timedelta
from typing import Optional

from git import Repo

from ..core import build_prompt, _extract_message_from_text


class ClaudeAI:
    """AI provider using `claude` CLI to draft commit messages.

    Caching is handled by the caller before invoking this provider.
    """

    def __init__(
        self,
        repo: Repo,
        diff: str,
        passthru: list[str],
        debug: bool = False,
        timeout: Optional[timedelta] = None,
        previous_message: Optional[str] = None,
    ):
        self.repo = repo
        self.diff = diff
        self.passthru = passthru
        self.debug = debug
        self.timeout = timeout
        self.previous_message = previous_message
        self.logger = logging.getLogger(__name__)

    async def generate(self, include_all: bool, model: str) -> str:
        # Build prompt from the provided diff and repo context
        prompt = build_prompt(
            self.repo,
            self.diff,
            self.passthru,
            self.previous_message,
        )

        # Truncate prompt if too long and warn (stderr) in debug mode only
        max_chars = int(os.environ.get("GIT_AI_MAX_PROMPT", "20000"))
        if len(prompt) >= max_chars:
            prompt = prompt[: max(0, max_chars - 100)] + "\n\n[TRUNCATED - prompt was too long]"
            if self.debug:
                print(
                    f"# Warning: Prompt truncated to {max_chars} chars",
                    file=sys.stderr,
                )

        cmd = [
            "claude",
            "--model",
            (model or "sonnet"),
            "-p",
            prompt,
            "--disallowedTools",
            "*",
        ]
        if self.debug:
            shell_cmd = subprocess.list2cmdline(cmd)
            self.logger.debug("Claude command:\n%s", shell_cmd)
            self.logger.debug("Claude prompt:\n%s", prompt)

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
                f"# Error: Claude command timed out after {secs_str} seconds",
                file=sys.stderr,
            )
            raise

        if self.debug and stderr:
            self.logger.debug("Claude stderr:\n%s", stderr.decode(errors="replace"))

        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode or 1, ["claude"], (stderr or b"").decode())

        response = (stdout or b"").decode().strip()
        return _extract_message_from_text(response)

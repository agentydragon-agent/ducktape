from __future__ import annotations


import logging
import subprocess
from datetime import timedelta
from typing import Optional

from git import Repo

from ._common import run_subprocess, build_prompt_for_claude, extract_message


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
    ) -> None:
        self.repo = repo
        self.diff = diff
        self.passthru = passthru
        self.debug = debug
        self.timeout = timeout
        self.previous_message = previous_message
        self.logger = logging.getLogger(__name__)

    async def generate(self, include_all: bool, model: str) -> str:  # include_all unused (kept for signature parity)
        prompt = build_prompt_for_claude(
            self.repo,
            self.diff,
            self.passthru,
            self.previous_message,
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

        rc, stdout_b, stderr_b = await run_subprocess(cmd, timeout=self.timeout, debug=self.debug, logger=self.logger)

        if self.debug and stderr_b:
            self.logger.debug("Claude stderr:\n%s", stderr_b.decode(errors="replace"))

        if rc != 0:
            raise subprocess.CalledProcessError(rc or 1, ["claude"], (stderr_b or b"").decode())

        response = (stdout_b or b"").decode().strip()
        return extract_message(response)

from datetime import timedelta
import logging
import os
from pathlib import Path
import subprocess

import pygit2

from ._common import build_prompt_for_codex, extract_message, run_subprocess


class CodexAI:
    """AI provider using `codex exec` to draft commit messages.

    Caching is handled by the caller before invoking this provider.
    """

    def __init__(
        self,
        repo: pygit2.Repository,
        debug: bool = False,
        codex_bin: str | None = None,
        timeout: timedelta | None = None,
        previous_message: str | None = None,
    ):
        self.repo = repo
        self.debug = debug
        self.codex_bin: str = codex_bin or os.environ.get("CODEX_BIN") or "codex"
        self.timeout = timeout
        self.previous_message = previous_message
        self.logger = logging.getLogger(__name__)

    async def generate(self, include_all: bool, model: str) -> str:
        """Run codex in read-only sandbox at repo root and return the commit message."""
        # Compute paths from pygit2.Repository
        git_dir = Path(self.repo.path)
        worktree_dir = Path(self.repo.workdir) if self.repo.workdir else None

        last_msg_path = git_dir / "codex_last_message.txt"

        prompt = build_prompt_for_codex(self.repo, include_all, self.previous_message)

        wd = worktree_dir if worktree_dir else git_dir
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

        rc, stdout_b, stderr_b = await run_subprocess(
            cmd,
            deadline=self.timeout,
            debug=self.debug,
            logger=self.logger,
        )

        if self.debug:
            if stdout_b:
                self.logger.debug(
                    "Codex stdout:\n%s",
                    stdout_b.decode(errors="replace"),
                )
            if stderr_b:
                self.logger.debug(
                    "Codex stderr:\n%s",
                    stderr_b.decode(errors="replace"),
                )

        if rc != 0:
            raise subprocess.CalledProcessError(
                rc or 1,
                cmd,
                (stderr_b or b"").decode(),
            )

        try:
            raw_last = last_msg_path.read_text()
        except Exception as e:
            raise RuntimeError("codex exec did not produce a last message file") from e

        return extract_message(raw_last)

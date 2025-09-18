"""
git-commit-ai

* Runs an AI agent (Claude or Codex) to draft the initial commit message shown in your editor.
* Runs repo's pre-commit hook **in parallel** so you don't wait twice.
* Caches per-repo for one week keyed by staged diff hash.

Call exactly like `git commit`; every flag is forwarded. Extra wrapper flags:

    --model PROVIDER:MODEL (default: claude:sonnet)
    --debug                Enable debug logging (shows exact AI command)
    --accept-ai            Commit immediately with the AI-drafted message (skip editor)

Note: Pass --no-verify to skip running pre-commit inside this wrapper. The final `git commit`
      is invoked with --no-verify to avoid running hooks twice.
      Passing -m/--message is not supported; this tool supplies the commit message.

Important: Do NOT install this as a prepare-commit-msg hook. Since this command
         calls `git commit` internally, it would create an infinite loop. Use
         this as a standalone command replacement for `git commit`.

Example
    git-commit-ai -a               # like "git commit -a"
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
import fcntl
import hashlib
import logging
import os
from pathlib import Path
import pty
import select
import shutil
import struct
import subprocess
import sys
import termios
import time

import pygit2

from adgn.llm.git_commit_ai.backends.claude_backend import ClaudeAI
from adgn.llm.git_commit_ai.backends.codex_backend import CodexAI
from adgn.llm.git_commit_ai.minicodex_backend import generate_commit_message_minicodex

from .core import _diff, _format_name_status, _format_status_porcelain

# ---------------------------------------------------------------------


# ---------- constants -------------------------------------------------
MAX_FILE_LINES = 400  # truncate each file's hunk lines (per-file preview)
# Global cap on total diff size sent to AI (characters)
MAX_TOTAL_DIFF_CHARS = 120_000
DEFAULT_MODEL = "claude:sonnet"
SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
MAX_VERBOSE_DIFF_LINES = 3000  # cap verbose diff lines under scissors
DEFAULT_AI_TIMEOUT = timedelta(seconds=60)  # shared subprocess timeout for providers


@dataclass
class AppConfig:
    provider: str
    model_name: str
    model_str: str
    timeout: timedelta | None

    @staticmethod
    def resolve(known) -> AppConfig:
        # Precedence: CLI args > env vars > defaults. No git config.
        model_str = (
            known.model or os.environ.get("GIT_COMMIT_AI_MODEL") or DEFAULT_MODEL
        )

        if getattr(known, "timeout_secs", None) is not None:
            raw_timeout_secs = known.timeout_secs
        else:
            raw_timeout_secs = int(DEFAULT_AI_TIMEOUT.total_seconds())
            if (
                env_timeout := os.environ.get("GIT_COMMIT_AI_TIMEOUT_SECS")
            ) is not None:
                with contextlib.suppress(ValueError):
                    raw_timeout_secs = int(env_timeout)

        timeout = None if raw_timeout_secs <= 0 else timedelta(seconds=raw_timeout_secs)

        if ":" in model_str:
            provider, model_name = model_str.split(":", 1)
            provider = provider.strip() or "claude"
            model_name = model_name.strip()
        else:
            provider, model_name = "claude", model_str.strip()

        return AppConfig(
            provider=provider,
            model_name=model_name,
            model_str=model_str,
            timeout=timeout,
        )


def _truncate_hunks(raw: str) -> str:
    """Truncate per-file hunk sections to MAX_FILE_LINES and rejoin, then cap total size.

    Notes:
    - Per-file: keep only first MAX_FILE_LINES lines of each file section.
    - Global: cap the final concatenated diff to MAX_TOTAL_DIFF_CHARS to protect model context.
    """
    cur: list[str] = []
    out: list[str] = []
    lines = 0
    for line in raw.splitlines():
        if line.startswith(("diff --git", "index ", "--- ", "+++ ")):
            if cur:
                out.append("\n".join(cur[:MAX_FILE_LINES]))
            cur, lines = [line], 0
        else:
            if lines < MAX_FILE_LINES:
                cur.append(line)
            lines += 1
    if cur:
        out.append("\n".join(cur[:MAX_FILE_LINES]))
    result = "\n\n".join(out)
    if len(result) > MAX_TOTAL_DIFF_CHARS:
        total = len(result)
        result = result[:MAX_TOTAL_DIFF_CHARS] + (
            f"\n\n# [TRUNCATED: showing first {MAX_TOTAL_DIFF_CHARS} of {total} characters]"
        )
    return result


def _build_amend_diff(repo: pygit2.Repository, passthru: list[str]) -> str:
    """Build amend-mode diff: original commit diff plus new changes."""
    parts: list[str] = []
    # Original commit
    # Original commit
    head = repo.revparse_single("HEAD").peel(pygit2.Commit)
    try:
        parent = repo.revparse_single("HEAD^").peel(pygit2.Commit)
        parts.append("=== Original commit diff (HEAD^ to HEAD) ===")
        parts.append(repo.diff(parent.tree, head.tree).patch or "")
    except KeyError:
        # First commit: diff from empty tree
        tb = repo.TreeBuilder()
        empty_tree = repo.get(tb.write())
        parts.append("=== Original commit content ===")
        parts.append(repo.diff(empty_tree, head.tree).patch or "")
    # New changes
    parts.append("\n=== New changes being added ===")
    include_all = ("-a" in passthru) or ("--all" in passthru)
    parts.append(_diff(repo, include_all).patch or "")
    return "\n".join(parts)


def get_commit_diff(
    repo: pygit2.Repository,
    passthru: list[str],
    previous_message: str | None = None,
) -> str:
    """Get the diff that would be committed with the given flags."""
    # Determine if there is anything to commit using pygit2 status/diff
    include_all = ("-a" in passthru) or ("--all" in passthru)
    diff = _diff(repo, include_all)
    if not (diff.patch or "").strip():
        return ""

    # Compute raw diff then apply per-file truncation
    raw = _build_amend_diff(repo, passthru) if previous_message else diff.patch or ""

    return _truncate_hunks(raw)


def get_short_commitish(repo: pygit2.Repository) -> str:
    """Get the short commit hash of HEAD (7-char prefix)."""
    commit = repo.revparse_single("HEAD").peel(pygit2.Commit)
    return str(commit.id)[:7]


def repo_cache_dir(repo: pygit2.Repository) -> Path:
    """Get the cache directory for storing individual cache files."""
    p = Path(repo.path) / "ai_commit_cache"
    p.mkdir(exist_ok=True)
    return p


def build_commit_template(repo: pygit2.Repository, passthru: list[str]) -> str:
    """Assemble the standard git commit template text (status, staged/unstaged/untracked, optional verbose diff)."""
    branch = repo.head.shorthand if not repo.head_is_detached else "HEAD detached"
    status_output = _format_status_porcelain(repo)
    template_text = f"""# Please enter the commit message for your changes. Lines starting
# with '#' will be ignored, and an empty message aborts the commit.
#
# On branch {branch}
#
"""
    staged_files = (_format_name_status(repo, include_all=False) or "").splitlines()
    if staged_files:
        template_text += "# Changes to be committed:\n"
        for line in staged_files:
            status, filename = line.split("\t", 1)
            status_map = {
                "A": "new file:",
                "M": "modified:",
                "D": "deleted:",
                "R": "renamed:",
            }
            status_text = status_map.get(status[0], status + ":")
            template_text += f"#\t{status_text.ljust(12)} {filename}\n"

    # Add unstaged changes if any
    unstaged = (_format_name_status(repo, include_all=True) or "").splitlines()
    if unstaged:
        template_text += """#
# Changes not staged for commit:
#   (use "git add <file>..." to update what will be committed
#   (use "git restore <file>..." to discard changes in working directory
"""
        for line in unstaged:
            status, filename = line.split("\t", 1)
            status_map = {"M": "modified:", "D": "deleted:"}
            status_text = status_map.get(status[0], status + ":")
            template_text += f"#\t{status_text.ljust(12)} {filename}\n"

    # Add untracked files if any
    untracked = [
        line[3:] for line in status_output.splitlines() if line.startswith("?? ")
    ]
    if untracked:
        # Blank commented spacer before untracked section (readability)
        template_text += "#\n"
        template_text += """# Untracked files:
#   (use "git add <file>..." to include in what will be committed)
"""
        for filename in untracked:
            template_text += f"#\t{filename}\n"

    # Always add scissors marker; verbose diff may be auto-enabled by git config
    template_text += "#\n"
    template_text += """# ------------------------ >8 ------------------------
# Do not modify or remove the line above.
# Everything below it will be ignored.
"""

    # Determine verbose per git semantics: '-v' flag OR commit.verbose=true
    include_verbose = ("-v" in passthru) or ("--verbose" in passthru)

    if include_verbose:
        diff_text = _diff(repo, include_all=False).patch or ""
        diff_lines = diff_text.splitlines()
        if len(diff_lines) > MAX_VERBOSE_DIFF_LINES:
            total = len(diff_lines)
            diff_lines = [
                *diff_lines[:MAX_VERBOSE_DIFF_LINES],
                f"# [TRUNCATED: showing first {MAX_VERBOSE_DIFF_LINES} of {total} lines]",
            ]
        # Comment diff lines for readability and to ensure they are ignored even without scissors
        template_text += "\n".join(f"# {ln}" for ln in diff_lines)

    return template_text


class Cache:
    def __init__(self, cache_dir: Path):
        self.dir = cache_dir

    def get(self, key: str) -> str | None:
        if (p := self.dir / f"{key}.txt").exists():
            return p.read_text()
        return None

    def __setitem__(self, key: str, entry: str):
        (self.dir / f"{key}.txt").write_text(entry)

    def prune(self):
        cache_ttl = timedelta(days=7)
        now_epoch_s = time.time()
        for path in self.dir.glob("*.txt"):
            if now_epoch_s - path.stat().st_mtime > cache_ttl.total_seconds():
                path.unlink()


class TaskStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskState:
    """Tracks the state of a single task."""

    def __init__(self, task):
        self.task = task
        self.start_time_s = time.monotonic()
        self._end_time_s = None

    @property
    def status(self):
        """Get current status based on task state."""
        if not self.task.done():
            return TaskStatus.RUNNING

        try:
            # If result() doesn't raise, the task succeeded
            self.task.result()
            return TaskStatus.SUCCESS
        except asyncio.CancelledError:
            return TaskStatus.CANCELLED
        except Exception:
            return TaskStatus.FAILED

    @property
    def completed(self):
        """Check if task is completed."""
        return self.status != TaskStatus.RUNNING

    @property
    def final_duration_s(self):
        """Get final duration of the task if completed, None otherwise."""
        if not self.completed:
            return None

        # Cache the duration the first time the task completes
        if self._end_time_s is None:
            self._end_time_s = time.monotonic()

        return self._end_time_s - self.start_time_s

    def cancel(self):
        """Cancel the task."""
        if not self.task.done():
            self.task.cancel()

    @property
    def done(self):
        """Check if task is done."""
        return self.task.done()


_ANSI_ON = sys.stdout.isatty()


def _ansi(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _ANSI_ON else text


_STATUS_ICONS: dict[TaskStatus, str] = {
    TaskStatus.RUNNING: _ansi("⏳", "33"),  # yellow
    TaskStatus.SUCCESS: _ansi("✓", "32"),  # green
    TaskStatus.FAILED: _ansi("✗", "31"),  # red
    TaskStatus.CANCELLED: _ansi("-", "2"),  # dim
}


class ParallelTaskRunner:
    """Manages parallel execution of pre-commit and AI message generation with a single-line status display."""

    def __init__(self, ai_state, precommit_state, master_fd):
        self.ai_state = ai_state
        self.precommit_state = precommit_state
        self.start_time_s = time.monotonic()
        self._status_visible = False  # Track if status line is currently visible

    async def _stream_output(self, master_fd):
        """Stream output from the file descriptor."""
        # Make fd non-blocking
        os.set_blocking(master_fd, False)

        def _read_chunk():
            try:
                if not (chunk := os.read(master_fd, 4096)):
                    return False  # EOF

                # Clear status line if it's visible
                self._clear_status_line()
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
                return True
            except OSError:
                return False  # Error reading

        try:
            while not self.precommit_state.task.done():
                readable, _, _ = select.select([master_fd], [], [], 0.01)
                if readable and not _read_chunk():
                    return  # EOF or error
                await asyncio.sleep(0)  # Yield to other tasks

            # Drain any remaining data
            while True:
                readable, _, _ = select.select([master_fd], [], [], 0.01)
                if not readable or not _read_chunk():
                    return  # No more data to read
                await asyncio.sleep(0)  # Yield to other tasks
        finally:
            os.close(master_fd)

    @classmethod
    async def create_and_run(
        cls,
        repo: pygit2.Repository,
        ai_task: asyncio.Task[str],
        run_precommit: bool = True,
    ) -> str:
        """Factory method that creates runner and manages task lifecycle."""
        precommit_path = Path(repo.path) / "hooks" / "pre-commit"
        output_task = None

        if run_precommit:
            master_fd, slave_fd = create_pty_with_terminal_size()

            # Check if pre-commit hook exists.
            async def run_precommit_wrapper():
                try:
                    if not (precommit_path.exists() and precommit_path.is_file()):
                        return  # No pre-commit hook, nothing to do
                    # Run pre-commit hook with given slave end of PTY.
                    proc = await asyncio.create_subprocess_exec(
                        precommit_path,
                        stdout=slave_fd,
                        stderr=slave_fd,
                        stdin=slave_fd,
                        env=os.environ.copy(),
                    )
                    returncode = await proc.wait()
                    if returncode != 0:
                        raise subprocess.CalledProcessError(
                            returncode,
                            str(precommit_path),
                        )
                finally:
                    os.close(slave_fd)

            precommit_task = asyncio.create_task(run_precommit_wrapper())
            runner = cls(TaskState(ai_task), TaskState(precommit_task), master_fd)
            update_task = asyncio.create_task(runner._update_loop())
            output_task = asyncio.create_task(runner._stream_output(master_fd))
        else:
            # Skip running pre-commit (e.g., --no-verify was passed)
            precommit_task = asyncio.create_task(asyncio.sleep(0))
            runner = cls(TaskState(ai_task), TaskState(precommit_task), None)
            update_task = asyncio.create_task(runner._update_loop())
        try:
            # Both tasks will raise exceptions on failure
            msg, _ = await asyncio.gather(ai_task, precommit_task)
        except subprocess.CalledProcessError as e:
            # Pre-commit hook failed
            # UI will have already shown the output and status
            sys.exit(e.returncode)
        except TimeoutError:
            # Provider timed out; exit with a standard timeout code
            sys.exit(124)
        except Exception:
            # One of the tasks failed - wait for both to complete before re-raising
            await asyncio.gather(ai_task, precommit_task, return_exceptions=True)
            raise
        finally:
            if not update_task.done():
                update_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await update_task
            # Clean up output streaming task
            if output_task and not output_task.done():
                output_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await output_task

        return msg

    def _clear_status_line(self):
        """Clear the current status line."""
        if self._status_visible:
            # Move cursor to beginning of line and clear it
            print("\r\033[2K", end="", flush=True)
            self._status_visible = False

    @property
    def elapsed_s(self):
        return time.monotonic() - self.start_time_s

    def _status_char(self):
        if self.ai_state.done and self.precommit_state.done:
            return "✓"  # Checkmark when all done
        # Spinner
        return SPINNER_CHARS[int(self.elapsed_s * 10) % len(SPINNER_CHARS)]

    def _print_status_line(self):
        """Print a simple status line using carriage return.

        TODO(mpokorny): Handle SIGWINCH (terminal resize) to ensure the status line
        doesn't jump to the bottom; re-evaluate cursor positioning strategy.
        """

        # Build status with fixed widths
        parts = [
            # Status character and elapsed time (fixed width)
            f"{self._status_char()} {self.elapsed_s:5.1f}s",
        ]
        # Task statuses with fixed alignment
        for state, label in [
            (self.precommit_state, "pre-commit"),
            (self.ai_state, "message"),
        ]:
            duration_str = f"{state.final_duration_s:.1f}s" if state.completed else ""
            # Fixed width for duration
            parts.append(f"{duration_str:<5} {_STATUS_ICONS[state.status]} {label}")

        status = " ".join(parts)
        # Truncate to fit terminal width. If we can't get size, use full status.
        with contextlib.suppress(OSError, ValueError):
            status = status[: shutil.get_terminal_size().columns - 1]
        print(f"\r{status}", end="", flush=True)
        self._status_visible = True

    async def _update_loop(self):
        """Update the display periodically."""
        while not (self.ai_state.done and self.precommit_state.done):
            # Cancel AI if pre-commit failed
            if self.precommit_state.status == TaskStatus.FAILED:
                self.ai_state.cancel()
            self._print_status_line()  # Update status line
            await asyncio.sleep(0.1)
        self._print_status_line()  # Final update with newline
        print()  # Move to next line after final status


def create_pty_with_terminal_size():
    """Create a PTY and set its size to match the current terminal."""
    master_fd, slave_fd = pty.openpty()

    # Early bailout if not a TTY; keep default size
    if not sys.stdout.isatty():
        return master_fd, slave_fd

    try:
        # Query terminal size using TIOCGWINSZ; use bytes buffer for type safety
        buf = struct.pack("HHHH", 0, 0, 0, 0)
        winsize = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, buf)
        rows, cols, _, _ = struct.unpack("HHHH", winsize)
        # Apply size to slave end
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except (OSError, struct.error):
        pass

    return master_fd, slave_fd


# ---------- helpers to reduce async_main complexity -------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--model")  # Resolved via layered config (env/git/default)
    parser.add_argument(
        "--timeout-secs", type=int, help="AI timeout seconds (<=0 disables)"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--accept-ai",
        action="store_true",
        help="Commit immediately with the AI-drafted message (skip editor)",
    )
    return parser


def _parse_args_and_passthru() -> tuple[argparse.Namespace, list[str]]:
    parser = _build_arg_parser()
    return parser.parse_known_args()


def _init_logging(repo: pygit2.Repository, debug: bool) -> logging.Logger:
    """Configure root logger to file (always) and stderr (when debug)."""
    log_file = Path(repo.path) / "git_commit_ai.log"
    file_handler = logging.FileHandler(log_file, mode="a")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s: %(message)s")
    )
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.handlers = [
        h for h in logger.handlers if not isinstance(h, logging.FileHandler)
    ]
    logger.addHandler(file_handler)
    if debug:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(console_handler)
    return logger


def _validate_no_message_flag(passthru: list[str]) -> None:
    if any(a in {"-m", "--message"} or a.startswith("--message=") for a in passthru):
        print(
            "Error: -m/--message is not supported; this tool supplies the commit message. "
            "Remove -m/--message and try again.",
            file=sys.stderr,
        )
        sys.exit(2)


def _stage_all_if_requested(repo: pygit2.Repository, passthru: list[str]) -> None:
    if "-a" in passthru or "--all" in passthru:
        # Stage tracked changes (approximate 'git add -u')
        repo.index.add_all()
        repo.index.write()


def _get_previous_message_if_amend(
    repo: pygit2.Repository, is_amend: bool
) -> str | None:
    if not is_amend:
        return None
    try:
        commit = repo.revparse_single("HEAD").peel(pygit2.Commit)
        return (commit.message or "").strip()
    except Exception as e:
        print(
            f"Error: Cannot amend - failed to retrieve previous commit message: {e}",
            file=sys.stderr,
        )
        sys.exit(1)


# ---------- commit/editor helpers ------------------------------------


def _make_stats_comment(cached: bool, diff: str, msg: str, elapsed_s: float) -> str:
    return (
        f"\n# ai-draft{'(cached)' if cached else ''}: prompt: {len(diff)} chars, "
        f"response: {len(msg)} chars, elapsed: {elapsed_s:.2f}s\n"
    )


async def _commit_immediately(msg: str, passthru: list[str]) -> None:
    if not msg.strip():
        print("Aborting commit due to empty AI commit message.", file=sys.stderr)
        sys.exit(1)
    commit_passthru = [arg for arg in passthru if arg not in ("-a", "--all")]
    commit_proc = await asyncio.create_subprocess_exec(
        "git",
        "commit",
        "-m",
        msg,
        "--no-verify",
        *commit_passthru,
    )
    exit_code = await commit_proc.wait()
    sys.exit(exit_code)


async def _run_editor_flow(
    repo: pygit2.Repository,
    msg: str,
    previous_message: str | None,
    stats_comment: str,
    passthru: list[str],
) -> None:
    final_text = msg
    if previous_message:
        final_text += "\n\n# Previous commit message (being amended):\n"
        for line in previous_message.splitlines():
            final_text += f"# {line}\n"
    final_text += stats_comment + build_commit_template(repo, passthru)

    commit_msg_path = Path(repo.path) / "COMMIT_EDITMSG"
    commit_msg_path.write_text(final_text)

    mtime_before = commit_msg_path.stat().st_mtime
    content_before = final_text

    editor = await _get_editor()
    commit_msg_path = Path(repo.path) / "COMMIT_EDITMSG"
    editor_proc = await asyncio.create_subprocess_shell(f"{editor} {commit_msg_path}")
    if (rc := await editor_proc.wait()) != 0:
        print(
            f"Aborting commit: editor exited with code {rc} (e.g., :cq)",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        final_content = commit_msg_path.read_text()
        mtime_after = commit_msg_path.stat().st_mtime
        saved = mtime_after != mtime_before
        changed = final_content.rstrip("\n") != content_before
        if not saved and not changed:
            print(
                "Aborting commit: editor closed without saving (unchanged commit message).",
                file=sys.stderr,
            )
            sys.exit(1)
    except FileNotFoundError:
        print("Aborting commit.", file=sys.stderr)
        sys.exit(1)

    content_lines: list[str] = []
    for line in final_content.splitlines():
        if line.startswith("# ------------------------ >8 ------------------------"):
            break
        if line.strip() and not line.strip().startswith("#"):
            content_lines.append(line)
    if not content_lines:
        print("Aborting commit due to empty commit message.", file=sys.stderr)
        sys.exit(1)

    commit_passthru = [arg for arg in passthru if arg not in ("-a", "--all")]
    commit_proc = await asyncio.create_subprocess_exec(
        "git",
        "commit",
        "-F",
        commit_msg_path,
        "--cleanup=strip",
        "--no-verify",
        *commit_passthru,
    )
    sys.exit(await commit_proc.wait())


@dataclass
class ProduceMessageInput:
    repo: pygit2.Repository
    provider: str
    model_name: str
    debug: bool
    deadline: timedelta | None
    passthru: list[str]
    diff: str
    previous_message: str | None
    cache: Cache
    key: str


async def _produce_message(inp: ProduceMessageInput) -> tuple[str, bool]:
    """Return (message, cached). Runs provider and pre-commit where applicable."""
    if (msg := inp.cache.get(inp.key)) is not None:
        return msg, True

    include_all = ("-a" in inp.passthru) or ("--all" in inp.passthru)

    if inp.provider == "claude":
        ai_client = ClaudeAI(
            inp.repo,
            diff=inp.diff,
            passthru=inp.passthru,
            debug=inp.debug,
            timeout=inp.deadline,
            previous_message=inp.previous_message,
        )
        ai_task: asyncio.Task[str] = asyncio.create_task(
            ai_client.generate(include_all, inp.model_name)
        )
    elif inp.provider == "codex":
        ai_client = CodexAI(
            inp.repo,
            debug=inp.debug,
            timeout=inp.deadline,
            previous_message=inp.previous_message,
        )
        ai_task = asyncio.create_task(ai_client.generate(include_all, inp.model_name))
    elif inp.provider == "minicodex":
        ai_task = asyncio.create_task(
            generate_commit_message_minicodex(
                model=inp.model_name or "gpt-5",
                debug=inp.debug,
            ),
        )
    else:
        raise ValueError(f"Unknown AI provider: {inp.provider}")

    run_precommit = "--no-verify" not in inp.passthru
    msg = await ParallelTaskRunner.create_and_run(
        inp.repo, ai_task, run_precommit=run_precommit
    )
    inp.cache[inp.key] = msg
    return msg, False


# ---------- main ------------------------------------------------------


async def _get_editor() -> str:
    # Get git's editor
    proc = await asyncio.create_subprocess_exec(
        "git",
        "var",
        "GIT_EDITOR",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _stderr = await proc.communicate()
    result_stdout = stdout.decode() if stdout else ""
    return (
        result_stdout.strip()
        if proc.returncode == 0
        else os.environ.get("EDITOR", "vi")
    )


async def async_main():
    start_monotonic_s = time.monotonic()
    gitdir = pygit2.discover_repository(str(Path.cwd()))
    if not gitdir:
        print(
            "fatal: not a git repository (or any of the parent directories)",
            file=sys.stderr,
        )
        sys.exit(128)
    repo = pygit2.Repository(gitdir)

    args, passthru = _parse_args_and_passthru()
    _validate_no_message_flag(passthru)

    # Detect --amend flag
    is_amend = "--amend" in passthru

    # Logging and config
    _init_logging(repo, args.debug)
    config = AppConfig.resolve(args)
    if args.debug:
        print(
            f"# Resolved model={config.model_str}, timeout={config.timeout}",
            file=sys.stderr,
        )

    # Stage if requested (-a/--all)
    _stage_all_if_requested(repo, passthru)

    # Get previous commit message if amending
    previous_message = _get_previous_message_if_amend(repo, is_amend)

    if not (diff := get_commit_diff(repo, passthru, previous_message)).strip():
        # Check if there's truly nothing to commit
        status = repo.git.status("--porcelain")
        if not status:
            print("nothing to commit, working tree clean", file=sys.stderr)
        else:
            # There are changes but -a wasn't passed
            print(
                'no changes added to commit (use "git add" and/or "git commit -a")',
                file=sys.stderr,
            )
        sys.exit(1)

    # provider:model parsing handled by AppConfig.resolve
    provider, model_name = config.provider, config.model_name
    include_all = ("-a" in passthru) or ("--all" in passthru)

    # Clean old cache entries
    cache = Cache(repo_cache_dir(repo))
    cache.prune()

    # Cache key by provider, model, scope, HEAD, diff, and amend status
    commitish = get_short_commitish(repo)
    diff_hash = hashlib.sha256(diff.encode()).hexdigest()
    scope = "all" if include_all else "staged"
    amend_marker = "amend" if previous_message else "new"
    key = f"{provider}:{model_name}:{scope}:{amend_marker}:{commitish}:{diff_hash}"

    msg, cached = await _produce_message(
        ProduceMessageInput(
            repo=repo,
            provider=provider,
            model_name=model_name,
            debug=args.debug,
            deadline=config.timeout,
            passthru=passthru,
            diff=diff,
            previous_message=previous_message,
            cache=cache,
            key=key,
        )
    )

    elapsed_s = time.monotonic() - start_monotonic_s
    stats_comment = _make_stats_comment(cached, diff, msg, elapsed_s)

    if args.accept_ai:
        await _commit_immediately(msg, passthru)

    await _run_editor_flow(repo, msg, previous_message, stats_comment, passthru)


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()

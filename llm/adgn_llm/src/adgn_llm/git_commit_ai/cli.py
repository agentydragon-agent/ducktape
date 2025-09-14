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

# ---------------------------------------------------------------------
from __future__ import annotations

import argparse
import asyncio
import contextlib
import fcntl
import hashlib
import logging
import os
import pty
import select
import shutil
import struct
import subprocess
import sys
import termios
import time
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from pathlib import Path

from git import Repo
from git.exc import GitCommandError
from adgn_llm.git_commit_ai.backends.claude_backend import ClaudeAI
from adgn_llm.git_commit_ai.backends.codex_backend import CodexAI

# ---------- constants -------------------------------------------------
MAX_FILE_LINES = 400  # truncate each file's hunk lines (per-file preview)
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
        model_str = known.model or os.environ.get("GIT_COMMIT_AI_MODEL") or DEFAULT_MODEL

        if getattr(known, "timeout_secs", None) is not None:
            raw_timeout_secs = known.timeout_secs
        else:
            raw_timeout_secs = int(DEFAULT_AI_TIMEOUT.total_seconds())
            if (env_timeout := os.environ.get("GIT_COMMIT_AI_TIMEOUT_SECS")) is not None:
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


def get_commit_diff(
    repo: Repo,
    passthru: list[str],
    previous_message: str | None = None,
) -> str:
    """Get the diff that would be committed with the given flags."""
    # First, check what would be committed with these flags
    dry_run = subprocess.run(
        ["git", "commit", "--dry-run", "-m", "_test_", *passthru],
        capture_output=True,
        text=True,
        check=False,
    )

    # If nothing to commit, return empty
    if dry_run.returncode != 0 and "nothing to commit" in dry_run.stdout:
        return ""

    # Now get the diff based on what would be committed
    if previous_message:  # amending
        # For amend, show BOTH original diff and new changes
        parts = []

        # First show what was in the original commit
        try:
            # Try to get diff from parent (if exists)
            parts.append("=== Original commit diff (HEAD^ to HEAD) ===")
            parts.append(repo.git.diff("HEAD^", "HEAD", "--unified=0"))
        except GitCommandError:
            # First commit (no parent), show HEAD content
            parts.append("=== Original commit content ===")
            parts.append(repo.git.show("HEAD", "--unified=0"))

        # Then show what's being added/changed
        parts.append("\n=== New changes being added ===")
        if "-a" in passthru or "--all" in passthru:
            # Show all working tree changes
            parts.append(repo.git.diff("HEAD", "--unified=0"))
        else:
            # Show only staged changes
            parts.append(repo.git.diff("--cached", "--unified=0"))

        raw = "\n".join(parts)
    elif "-a" in passthru or "--all" in passthru:
        # Show diff of all tracked files
        raw = repo.git.diff("HEAD", "--unified=0")
    else:
        # Show only staged changes
        raw = repo.git.diff("--cached", "--unified=0")

    cur: list[str] = []
    out, lines = [], 0
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
    return "\n\n".join(out)


def get_short_commitish(repo: Repo) -> str:
    """Get the short commit hash of HEAD."""
    return repo.git.rev_parse("HEAD", short=True)


def repo_cache_dir(repo: Repo) -> Path:
    """Get the cache directory for storing individual cache files."""
    p = Path(repo.git_dir) / "ai_commit_cache"
    p.mkdir(exist_ok=True)
    return p


def build_commit_template(repo: Repo, passthru: list[str]) -> str:
    """Assemble the standard git commit template text (status, staged/unstaged/untracked, optional verbose diff)."""
    branch = repo.active_branch.name if not repo.head.is_detached else "HEAD detached"
    status_output = repo.git.status("--porcelain")
    template_text = f"""# Please enter the commit message for your changes. Lines starting
# with '#' will be ignored, and an empty message aborts the commit.
#
# On branch {branch}
#
"""
    staged_files = repo.git.diff("--cached", "--name-status").splitlines()
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
    unstaged = repo.git.diff("--name-status").splitlines()
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
    untracked = [line[3:] for line in status_output.splitlines() if line.startswith("?? ")]
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
    if not include_verbose:
        try:
            val = repo.git.config("--get", "commit.verbose")
        except GitCommandError:
            pass
        else:
            if str(val).strip().lower() in {"true", "1", "yes", "on"}:
                include_verbose = True

    if include_verbose:
        diff_text = repo.git.diff("--cached")
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
    async def create_and_run(cls, repo, ai_task, run_precommit: bool = True) -> str:
        """Factory method that creates runner and manages task lifecycle."""
        precommit_path = Path(repo.git_dir) / "hooks" / "pre-commit"
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
        try:
            status = status[: shutil.get_terminal_size().columns - 1]
        except (OSError, ValueError):
            pass
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
        winsize = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, "        ")
        rows, cols = struct.unpack("hh", winsize[:4])
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("hh", rows, cols))
    except (OSError, struct.error):
        pass

    return master_fd, slave_fd


# ---------- main ------------------------------------------------------


async def _get_editor():
    # Get git's editor
    proc = await asyncio.create_subprocess_exec(
        "git",
        "var",
        "GIT_EDITOR",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    result_stdout = stdout.decode() if stdout else ""
    return result_stdout.strip() if proc.returncode == 0 else os.environ.get("EDITOR", "vi")


async def async_main():
    start_monotonic_s = time.monotonic()
    repo = Repo(Path.cwd(), search_parent_directories=True)

    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--model")  # Resolved via layered config (env/git/default)
    parser.add_argument(
        "--timeout-secs",
        type=int,
        help="AI timeout seconds (<=0 disables)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--accept-ai",
        action="store_true",
        help="Commit immediately with the AI-drafted message (skip editor)",
    )
    args, passthru = parser.parse_known_args()

    # Disallow -m/--message; the tool generates the commit message
    if any(a in {"-m", "--message"} or a.startswith("--message=") for a in passthru):
        print(
            "Error: -m/--message is not supported; this tool supplies the commit message. "
            "Remove -m/--message and try again.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Detect --amend flag
    is_amend = "--amend" in passthru

    # Configure logging - always log to file under .git/
    log_file = Path(repo.git_dir) / "git_commit_ai.log"

    # Always log to file
    file_handler = logging.FileHandler(log_file, mode="a")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s: %(message)s"),
    )

    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    # Resolve configuration
    config = AppConfig.resolve(args)
    if args.debug:
        print(
            f"# Resolved model={config.model_str}, timeout={config.timeout}",
            file=sys.stderr,
        )

    if args.debug:
        # Also log to stderr when debug is enabled
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(console_handler)

    # If -a/--all is passed, mirror `git commit -a`: stage tracked modifications/deletions now.
    # We intentionally do not unstage on failure/abort to match native git behavior.
    if "-a" in passthru or "--all" in passthru:
        repo.git.add("-u")

    # Get previous commit message if amending
    previous_message = None
    if is_amend:
        try:
            previous_message = repo.git.log("-1", "--pretty=format:%B").strip()
        except Exception as e:
            print(
                f"Error: Cannot amend - failed to retrieve previous commit message: {e}",
                file=sys.stderr,
            )
            sys.exit(1)

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

    if msg := cache.get(key):
        cached = True
    else:
        # Select provider client
        if provider == "claude":
            ai_client = ClaudeAI(
                repo,
                diff=diff,
                passthru=passthru,
                debug=args.debug,
                timeout=config.timeout,
                previous_message=previous_message,
            )
        elif provider == "codex":
            ai_client = CodexAI(
                repo,
                debug=args.debug,
                timeout=config.timeout,
                previous_message=previous_message,
            )
        elif provider == "minicodex":
            from adgn_llm.git_commit_ai.minicodex_backend import generate_commit_message_minicodex

            # Wrap as a task to reuse the runner logic below
            ai_task = asyncio.create_task(generate_commit_message_minicodex(model=model_name or "gpt-5"))
            run_precommit = "--no-verify" not in passthru
            msg = await ParallelTaskRunner.create_and_run(
                repo,
                ai_task,
                run_precommit=run_precommit,
            )
            cache[key] = msg
            cached = False
            # Skip legacy provider runner path
            elapsed_s = time.monotonic() - start_monotonic_s
            stats_comment = (
                f"\n# ai-draft{'(cached)' if cached else ''}: prompt: {len(diff)} chars, "
                f"response: {len(msg)} chars, elapsed: {elapsed_s:.2f}s\n"
            )
            # Continue into existing editor/commit flow using msg set above
            # (fall through)
        else:
            raise ValueError(f"Unknown AI provider: {provider}")

        # Factor out task creation to a single place
        if provider != "minicodex":
            ai_task = asyncio.create_task(ai_client.generate(include_all, model_name))
        # Respect --no-verify to skip running pre-commit inside this wrapper
        run_precommit = "--no-verify" not in passthru
        msg = await ParallelTaskRunner.create_and_run(
            repo,
            ai_task,
            run_precommit=run_precommit,
        )
        cache[key] = msg
        cached = False

    elapsed_s = time.monotonic() - start_monotonic_s
    stats_comment = (
        f"\n# ai-draft{'(cached)' if cached else ''}: prompt: {len(diff)} chars, "
        f"response: {len(msg)} chars, elapsed: {elapsed_s:.2f}s\n"
    )

    # Fast-path: commit immediately with AI message when requested
    if args.accept_ai:
        # Ensure non-empty message
        if not msg.strip():
            print("Aborting commit due to empty AI commit message.", file=sys.stderr)
            sys.exit(1)
        # Do not forward -a/--all; we've already staged via `git add -u`.
        # Also drop any existing -m/--message to avoid conflicts.
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

    # Combine everything for editor flow
    final_text = msg

    # Add previous message in comments if amending
    if previous_message:
        final_text += "\n\n# Previous commit message (being amended):\n"
        for line in previous_message.splitlines():
            final_text += f"# {line}\n"

    # Add stats and template (same for both cases)
    final_text += stats_comment + build_commit_template(repo, passthru)

    # Use git's COMMIT_EDITMSG for a more authentic experience (no trailing blank line)
    commit_msg_path = Path(repo.git_dir) / "COMMIT_EDITMSG"
    commit_msg_path.write_text(final_text)

    # Store the file's modification time and content before editing
    mtime_before = commit_msg_path.stat().st_mtime
    content_before = final_text

    # Run the editor
    editor = await _get_editor()
    commit_msg_path = Path(repo.git_dir) / "COMMIT_EDITMSG"
    editor_proc = await asyncio.create_subprocess_shell(f"{editor} {commit_msg_path}")
    if (rc := await editor_proc.wait()) != 0:
        print(
            f"Aborting commit: editor exited with code {rc} (e.g., :cq)",
            file=sys.stderr,
        )
        sys.exit(1)

    # Check what happened
    try:
        final_content = commit_msg_path.read_text()
        mtime_after = commit_msg_path.stat().st_mtime

        # Decide based on save vs change:
        saved = mtime_after != mtime_before
        changed = final_content.rstrip("\n") != content_before

        # If user exited without saving and nothing changed, abort (e.g., :q)
        if not saved and not changed:
            print(
                "Aborting commit: editor closed without saving (unchanged commit message).",
                file=sys.stderr,
            )
            sys.exit(1)
    except FileNotFoundError:
        print("Aborting commit.", file=sys.stderr)
        sys.exit(1)

    # Check for empty message (ignore comments and anything below scissors)
    content_lines: list[str] = []
    for line in final_content.splitlines():
        if line.startswith("# ------------------------ >8 ------------------------"):
            break
        if line.strip() and not line.strip().startswith("#"):
            content_lines.append(line)
    if not content_lines:
        print("Aborting commit due to empty commit message.", file=sys.stderr)
        sys.exit(1)

    # Now do the actual commit with the message
    # Do not forward -a/--all to final commit; we've already staged via `git add -u`.
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


# NOTE: Backends have been moved to adgn_llm.git_commit_ai.backends.*
# This module now imports ClaudeAI and CodexAI from those packages.


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
git-commit-ai

* Streams Claude (Anthropic) to draft the initial commit message shown in your editor.
* Runs the repo's pre-commit hook **in parallel** so you don't wait twice.
* Caches per-repo for one week keyed by staged diff hash.
* Limits diff context per file and prepends diffstat.
* Debug mode (`--debug`) prints prompt / response sizes, timing, and cost; those stats are also
  appended as comment lines in the template so they're visible while you edit.

Call exactly like `git commit`; every flag is forwarded. Extra wrapper flags:

    --model MODEL          (default: sonnet)
    --debug                verbose timings & token/cost info

Example
    git-commit-ai -a               # like “git commit -a”
"""

# ---------------------------------------------------------------------
import argparse
import asyncio
import contextlib
import fcntl
import hashlib
import os
import pty
import re
import select
import struct
import subprocess
import sys
import termios
import time
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import ClassVar

import yaml
from git import Repo
from rich.console import Console
from rich.table import Table
from rich.text import Text

# ---------- constants -------------------------------------------------
MAX_FILE_LINES = 400  # truncate each file's hunk lines
PAST_COMMITS_MAX_CHARS = 6000  # history context ceiling
SPINNER_INTERVAL = 0.1
DEFAULT_MODEL = "sonnet"

COMMIT_MESSAGE_PROMPT = """Write a concise, imperative-mood Git commit message. Output ONLY the commit message between <message> and </message> tags.
No explanations, no markdown, no signatures. Do NOT include 'Generated with' or 'Co-Authored-By' lines.

Example outputs:
<message>
Add user authentication to API endpoints
</message>

<message>
Refactor database connection handling

- Extract connection pool logic into separate module
- Add retry mechanism for transient failures
- Update all database queries to use new pool
</message>

Below, the staged diff is trimmed per file and preceded by a diffstat for context.

{diffstat}

{diff}"""


# ---------------------------------------------------------------------
class PromptBuilder:
    def __init__(self, repo: Repo, diff: str, diffstat: str):
        self.repo = repo
        self.parts = [COMMIT_MESSAGE_PROMPT.format(diffstat=diffstat, diff=diff)]
        self._append_history()

    def _append_history(self):
        chars = 0
        for commit in self.repo.iter_commits("HEAD", max_count=100):
            msg = commit.message.split("\n\n")[0]  # subject line only
            block = f"- {msg}"
            if chars + len(block) > PAST_COMMITS_MAX_CHARS:
                break
            self.parts.append(block)
            chars += len(block)

    def build(self) -> str:
        return (
            "\n\nPast commits:\n"
            + "\n".join(self.parts[1:])
            + "\n\n###\n\n"
            + self.parts[0]
        )

    @staticmethod
    def get_commit_diff(repo: Repo, passthru: list[str]) -> str:
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
        if "-a" in passthru or "--all" in passthru:
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


# ---------- helpers ---------------------------------------------------


def diffstat(repo: Repo, passthru: list[str]) -> str:
    """Get diffstat for what would be committed."""
    if "-a" in passthru or "--all" in passthru:
        return repo.git.diff("HEAD", "--stat")
    return repo.git.diff("--cached", "--stat")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def get_short_commitish(repo: Repo) -> str:
    """Get the short commit hash of HEAD."""
    return repo.git.rev_parse("HEAD", short=True)


def repo_cache_dir(repo: Repo) -> Path:
    """Get the cache directory for storing individual cache files."""
    p = Path(repo.git_dir) / "ai_commit_cache"
    p.mkdir(exist_ok=True)
    return p


class Cache:
    def __init__(self, dir: Path):
        self.dir = dir

    def compute_key(self, repo: Repo, diff: str) -> str:
        """Compute cache key from commitish and diff."""
        commitish = get_short_commitish(repo)
        return f"{commitish}_{sha(diff)}"

    def load(self, key: str) -> dict | None:
        """Load a single cache entry from its file."""
        path = self.dir / f"{key}.yaml"
        return yaml.safe_load(path.read_text()) if path.exists() else None

    def save(self, key: str, entry: dict):
        """Save a single cache entry to its file."""
        path = self.dir / f"{key}.yaml"
        path.write_text(yaml.dump(entry))

    def clean_old(self):
        """Remove cache entries older than TTL based on file modification time."""
        cache_ttl = timedelta(days=7)
        now = time.time()
        for path in self.dir.glob("*.yaml"):
            if now - path.stat().st_mtime > cache_ttl.total_seconds():
                path.unlink()


class TaskStatus(Enum):
    """Status of a task."""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskState:
    """Tracks the state of a single task."""

    def __init__(self, task):
        self.task = task
        self.start_time = time.time()

    @property
    def status(self):
        """Get current status based on task state."""
        if not self.task.done():
            return TaskStatus.RUNNING

        try:
            self.task.result()
            return TaskStatus.SUCCESS
        except asyncio.CancelledError:
            return TaskStatus.CANCELLED
        except Exception:
            return TaskStatus.FAILED

    @property
    def duration(self):
        """Get task duration if completed, None otherwise."""
        if self.status == TaskStatus.RUNNING:
            return None
        return time.time() - self.start_time

    def cancel(self):
        """Cancel the task."""
        if not self.task.done():
            self.task.cancel()

    def is_complete(self):
        """Check if task is done."""
        return self.task.done()


class RunningContext:
    """Context for a running ParallelTaskRunner."""

    def __init__(self, runner):
        self.runner = runner
        self.update_task = asyncio.create_task(self.runner._update_loop())

    async def stop(self):
        """Stop the update loop."""
        if not self.update_task.done():
            self.update_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.update_task


class ParallelTaskRunner:
    """Manages parallel execution of pre-commit and AI message generation with Rich UI."""

    def __init__(self, ai_state, precommit_state):
        self.ai_state = ai_state
        self.precommit_state = precommit_state
        self.console = Console()
        self.start_time = time.time()
        self._context = None
        self._output_fd = None
        self._output_task = None
        self._output_lines = []  # Buffer output lines
        self._last_output_had_newline = True  # Track if last output ended with newline
        self._status_on_own_line = True  # Track if status is on its own line
        self._last_output_time = 0  # Track when we last received output

    def set_output_fd(self, fd):
        """Set file descriptor to read output from."""
        self._output_fd = fd
        self._output_task = asyncio.create_task(self._stream_output())

    def _drain_fd(self, timeout: float = 0) -> bool:
        """Drain available data from fd. Returns True if EOF or error."""
        readable, _, _ = select.select([self._output_fd], [], [], timeout)
        if not readable:
            return False

        try:
            data = os.read(self._output_fd, 4096)
            if not data:
                return True  # EOF

            # If we need a newline before the status bar, ensure we track it
            self._last_output_had_newline = data.endswith(b"\n")

            # Stop live temporarily to write output
            if self._context and self._context.live._started:
                self._context.live.stop()

            # Print output directly to console
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()

            # Restart live display with proper positioning
            if self._context:
                # Ensure we're on a new line for the status bar
                if not self._last_output_had_newline:
                    sys.stdout.buffer.write(b"\n")
                    sys.stdout.buffer.flush()
                self._context.live.start()

        except OSError:
            return True  # Error reading
        return False

    async def _stream_output(self):
        """Stream output from the file descriptor."""
        if self._output_fd is None:
            return

        # Make fd non-blocking
        os.set_blocking(self._output_fd, False)

        try:
            while True:
                readable, _, _ = select.select([self._output_fd], [], [], 0.01)

                if readable:
                    try:
                        data = os.read(self._output_fd, 4096)
                        if not data:
                            break  # EOF
                        # Track if output ends with newline
                        self._last_output_had_newline = data.endswith(b"\n")
                        # Just write the output directly - no Rich interference
                        sys.stdout.buffer.write(data)
                        sys.stdout.buffer.flush()
                        # If we just wrote output, status is no longer on its own line
                        self._status_on_own_line = False
                        # Record when we last received output
                        self._last_output_time = time.time()
                    except OSError:
                        break  # Error reading

                # Check if pre-commit is done
                if self.precommit_state.task.done():
                    # Drain any remaining data
                    while True:
                        readable, _, _ = select.select([self._output_fd], [], [], 0)
                        if not readable:
                            break
                        try:
                            data = os.read(self._output_fd, 4096)
                            if not data:
                                break
                            # Track if output ends with newline
                            self._last_output_had_newline = data.endswith(b"\n")
                            sys.stdout.buffer.write(data)
                            sys.stdout.buffer.flush()
                            # If we just wrote output, status is no longer on its own line
                            self._status_on_own_line = False
                            # Record when we last received output
                            self._last_output_time = time.time()
                        except OSError:
                            break
                    break

                await asyncio.sleep(0)  # Yield to other tasks
        finally:
            os.close(self._output_fd)
            self._output_fd = None

    @classmethod
    async def create_and_run(cls, ai_task) -> str:
        """Factory method that creates runner and manages task lifecycle."""
        repo = Repo(Path.cwd(), search_parent_directories=True)

        # Check if pre-commit hook exists
        hook_path = Path(repo.git_dir) / "hooks" / "pre-commit"
        has_precommit = hook_path.exists() and hook_path.is_file()

        # Create PTY for pre-commit if needed
        if has_precommit:
            master_fd, slave_fd = create_pty_with_terminal_size()
        else:
            master_fd = slave_fd = None

        # Create placeholder for precommit task
        precommit_placeholder = TaskState(asyncio.Future())

        # Create runner
        runner = cls(TaskState(ai_task), precommit_placeholder)

        # Set up output streaming if we have pre-commit
        if has_precommit:
            runner.set_output_fd(master_fd)

        # Now create real precommit task
        async def run_precommit_wrapper():
            if not has_precommit:
                return 0
            try:
                return await run_precommit_process(slave_fd)
            finally:
                if slave_fd is not None:
                    os.close(slave_fd)

        precommit_task = asyncio.create_task(run_precommit_wrapper())
        precommit_placeholder.task = precommit_task

        async with runner:
            # Wait for both tasks
            try:
                msg, precommit_rc = await asyncio.gather(ai_task, precommit_task)
            except Exception:
                # One of the tasks failed - wait for both to complete before re-raising
                await asyncio.gather(ai_task, precommit_task, return_exceptions=True)
                raise

            if precommit_rc != 0:
                # The UI will have already shown the output and status
                sys.exit(precommit_rc)

        return msg

    _STATUS_ICONS: ClassVar[dict[TaskStatus, Text]] = {
        TaskStatus.RUNNING: Text("⏳", style="yellow"),
        TaskStatus.SUCCESS: Text("✓", style="green"),
        TaskStatus.FAILED: Text("✗", style="red"),
        TaskStatus.CANCELLED: Text("-", style="dim"),
    }

    @classmethod
    def _get_status_icon(cls, status):
        """Get status icon with color."""
        return cls._STATUS_ICONS[status]

    def _format_task_status(self, task_state: TaskState, label: str) -> str:
        """Format a task's status string."""
        icon = self._get_status_icon(task_state.status)
        duration_str = f"{task_state.duration:.1f}s " if task_state.duration else ""
        return f"[{duration_str}{icon}] {label}"

    def _print_status_line(self):
        """Print a simple status line using carriage return."""
        # If we just received output, wait a bit before updating status
        # This prevents mixing status bar with partial pre-commit output
        time_since_output = time.time() - self._last_output_time
        if time_since_output < 0.05 and not self._last_output_had_newline:
            # We just got output that didn't end with newline, skip this update
            return

        elapsed = time.time() - self.start_time

        # Spinner
        spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        spinner_index = int(elapsed * 10) % len(spinner_chars)
        ai_running = self.ai_state.status == TaskStatus.RUNNING
        precommit_running = self.precommit_state.status == TaskStatus.RUNNING
        spinner = (
            spinner_chars[spinner_index] if (ai_running or precommit_running) else ""
        )

        # Build simple status line
        parts = []
        if spinner:
            parts.append(spinner)
        parts.append(f"{elapsed:.1f}s")

        # Task statuses (without Rich markup)
        for task_state, label in [
            (self.precommit_state, "pre-commit"),
            (self.ai_state, "message"),
        ]:
            # Extract the icon character directly from the Rich Text object
            icon = str(self._get_status_icon(task_state.status))
            duration_str = f"{task_state.duration:.1f}s " if task_state.duration else ""
            parts.append(f"[{duration_str}{icon}] {label}")

        # Print with carriage return to overwrite
        status = " ".join(parts)
        # Pad with spaces to clear any remaining characters from previous lines
        terminal_width = 80  # Conservative default
        try:
            import shutil

            terminal_width = shutil.get_terminal_size().columns
        except Exception:
            pass

        # Ensure status fits in terminal
        status = status[: terminal_width - 1]

        # Always ensure we're on a clean line for the status bar
        if not self._status_on_own_line:
            # We need to get to a clean line
            if not self._last_output_had_newline:
                # Previous output didn't end with newline, add one
                print()  # This ensures we're on a new line
            # Now print the status
            print(f"\r{status}", end="", flush=True)
        else:
            # We're already on our own line, just update it
            print(f"\r\033[2K{status}", end="", flush=True)

        # Mark that status is now on its own line
        self._status_on_own_line = True

    def _create_status_table(self):
        """Create the status bar table."""
        elapsed = time.time() - self.start_time

        # Build status line components
        table = Table(show_header=False, box=None, padding=0)
        table.add_column()

        # Spinner or elapsed time
        spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        spinner_index = int(elapsed * 10) % len(spinner_chars)
        ai_running = self.ai_state.status == TaskStatus.RUNNING
        precommit_running = self.precommit_state.status == TaskStatus.RUNNING
        spinner = (
            spinner_chars[spinner_index] if (ai_running or precommit_running) else ""
        )

        # Build status text
        status_parts = []
        if spinner:
            status_parts.append(f"[cyan]{spinner}[/cyan]")
        status_parts.append(f"[dim]{elapsed:.1f}s[/dim]")

        # Add task statuses
        status_parts.append(
            self._format_task_status(self.precommit_state, "pre-commit"),
        )
        status_parts.append(self._format_task_status(self.ai_state, "message"))

        status_line = Text.from_markup(" ".join(str(p) for p in status_parts))
        table.add_row(status_line)
        return table

    def _create_display(self):
        """Create the full display with output and status."""
        # Don't show output in the Live display - it's printed directly
        # Just show the status bar
        return self._create_status_table()

    async def __aenter__(self):
        self._context = RunningContext(self)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._context:
            await self._context.stop()
            self._context = None

        # Clean up output streaming task
        if self._output_task and not self._output_task.done():
            self._output_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._output_task

    async def _update_loop(self):
        """Update the display periodically."""
        # Print initial status
        self._print_status_line()

        while True:
            # Check pre-commit exit code
            self._check_precommit_exit_code()

            # Cancel AI if pre-commit failed
            self._cancel_ai_if_precommit_failed()

            # Update status line
            self._print_status_line()

            # Exit when both tasks are done
            if self._both_done():
                break

            await asyncio.sleep(0.1)

        # Final update with newline
        self._print_status_line()
        print()  # Move to next line after final status

    def _check_precommit_exit_code(self):
        """Check pre-commit exit code and update status if needed."""
        if not self.precommit_state.task.done():
            return
        if self.precommit_state.status != TaskStatus.SUCCESS:
            return

        with contextlib.suppress(Exception):
            if self.precommit_state.task.result() != 0:
                self.precommit_state.status = TaskStatus.FAILED

    def _cancel_ai_if_precommit_failed(self):
        """Cancel AI task if pre-commit failed."""
        if self.precommit_state.status != TaskStatus.FAILED:
            return

        self.ai_state.cancel()

    def _both_done(self):
        """Check if both tasks are done and statuses are updated."""
        return self.ai_state.is_complete() and self.precommit_state.is_complete()


async def ask_claude(prompt: str, model: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "claude",
        "--model",
        model,
        "-p",
        prompt,
        "--disallowedTools",
        "*",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode or 1,  # Use 1 as default if returncode is None
            ["claude"],
            stderr.decode(),
        )

    response = stdout.decode().strip()

    # Extract message from between tags
    if match := re.search(r"<message>\s*(.*?)\s*</message>", response, re.DOTALL):
        return match.group(1).strip()
    # Fallback if tags are missing
    return response


def create_pty_with_terminal_size():
    """Create a PTY and set its size to match the current terminal."""
    master_fd, slave_fd = pty.openpty()

    # Set the terminal size to match the current terminal
    if sys.stdout.isatty():
        try:
            winsize = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, "        ")
            rows, cols = struct.unpack("hh", winsize[:4])
            fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("hh", rows, cols))
        except (OSError, struct.error):
            pass  # Ignore errors in terminal size setting

    return master_fd, slave_fd


async def run_precommit_process(slave_fd):
    """Run pre-commit hook with given slave end of PTY."""
    repo = Repo(Path.cwd(), search_parent_directories=True)
    hook_path = Path(repo.git_dir) / "hooks" / "pre-commit"
    proc = await asyncio.create_subprocess_exec(
        str(hook_path),
        stdout=slave_fd,
        stderr=slave_fd,
        stdin=slave_fd,
        env=os.environ.copy(),
    )
    return await proc.wait()


def token_estimate(text: str) -> int:
    return int(len(text) / 4)  # crude ≈4 chars / token


async def generate_fresh_commit_message(
    diff: str,
    passthru: list[str],
    model: str,
) -> str:
    """Generate a fresh commit message (non-cached case) while running pre-commit in parallel."""
    repo = Repo(Path.cwd(), search_parent_directories=True)
    diffstat_txt = diffstat(repo, passthru)
    prompt = PromptBuilder(repo, diff, diffstat_txt).build()

    # Create AI task
    ai_task = asyncio.create_task(ask_claude(prompt, model))

    return await ParallelTaskRunner.create_and_run(ai_task)


# ---------- main ------------------------------------------------------
def cleanup_staged_files(repo: Repo, staged_for_precommit: bool) -> None:
    """Reset staged files if they were staged temporarily for pre-commit."""
    if staged_for_precommit:
        repo.index.reset()


async def async_main():
    start = time.time()
    repo = Repo(Path.cwd(), search_parent_directories=True)

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--debug", action="store_true")
    known, passthru = parser.parse_known_args()

    # If --all or -a is passed, we need to stage files before running pre-commit
    # Pre-commit only runs on staged files
    staged_for_precommit = False
    if "-a" in passthru or "--all" in passthru:
        # Get list of modified/deleted tracked files with their status
        # Format: "M\tfilename" or "D\tfilename"
        changed_files = repo.git.diff("--name-status").splitlines()
        if changed_files:
            files_to_add = []
            files_to_remove = []
            for line in changed_files:
                if "\t" in line:
                    status, filename = line.split("\t", 1)
                    if status == "M":  # Modified
                        files_to_add.append(filename)
                    elif status == "D":  # Deleted
                        files_to_remove.append(filename)

            # Stage the changes
            if files_to_add:
                repo.index.add(files_to_add)
            if files_to_remove:
                repo.index.remove(files_to_remove)

            staged_for_precommit = bool(files_to_add or files_to_remove)

    diff = PromptBuilder.get_commit_diff(repo, passthru)
    if not diff.strip():
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

    now = datetime.utcnow().timestamp()

    # Clean old cache entries
    cache = Cache(repo_cache_dir(repo))
    cache.clean_old()
    key = cache.compute_key(repo, diff)
    entry = cache.load(key)
    if entry:
        msg = entry["msg"]
        cached = True
    else:
        msg = await generate_fresh_commit_message(diff, passthru, known.model)
        commitish = get_short_commitish(repo)
        entry = {"msg": msg, "ts": now, "commitish": commitish}
        cache.save(key, entry)
        cached = False

    elapsed = time.time() - start
    stats_comment = (
        f"# ai-draft {'(cached)' if cached else ''}\n"
        f"# prompt chars: {len(diff)}  ~{token_estimate(diff)}tok\n"
        f"# response chars: {len(msg)}  elapsed: {elapsed:.2f}s\n"
    )
    if known.debug:
        print(stats_comment.replace("# ", ""), file=sys.stderr)

    # Get git status information for the commit template
    branch = repo.active_branch.name if not repo.head.is_detached else "HEAD detached"
    status_output = repo.git.status("--porcelain")

    # Build the standard git commit template
    git_template = []
    git_template.append("")
    git_template.append(
        "# Please enter the commit message for your changes. Lines starting",
    )
    git_template.append(
        "# with '#' will be ignored, and an empty message aborts the commit.",
    )
    git_template.append("#")
    git_template.append(f"# On branch {branch}")
    git_template.append("#")

    # Add list of changes to be committed
    staged_files = repo.git.diff("--cached", "--name-status").splitlines()
    if staged_files:
        git_template.append("# Changes to be committed:")
        for line in staged_files:
            status, filename = line.split("\t", 1)
            status_map = {
                "A": "new file:",
                "M": "modified:",
                "D": "deleted:",
                "R": "renamed:",
            }
            status_text = status_map.get(status[0], status + ":")
            git_template.append(f"#\t{status_text.ljust(12)} {filename}")

    # Add unstaged changes if any
    unstaged = repo.git.diff("--name-status").splitlines()
    if unstaged:
        git_template.append("#")
        git_template.append("# Changes not staged for commit:")
        git_template.append(
            '#   (use "git add <file>..." to update what will be committed)',
        )
        git_template.append(
            '#   (use "git restore <file>..." to discard changes in working directory)',
        )
        for line in unstaged:
            status, filename = line.split("\t", 1)
            status_map = {"M": "modified:", "D": "deleted:"}
            status_text = status_map.get(status[0], status + ":")
            git_template.append(f"#\t{status_text.ljust(12)} {filename}")

    # Add untracked files if any
    untracked = [
        line[3:] for line in status_output.splitlines() if line.startswith("?? ")
    ]
    if untracked:
        git_template.append("#")
        git_template.append("# Untracked files:")
        git_template.append(
            '#   (use "git add <file>..." to include in what will be committed)',
        )
        for filename in untracked:
            git_template.append(f"#\t{filename}")

    git_template.append("#")

    # Add verbose diff if requested
    if "-v" in passthru or "--verbose" in passthru:
        git_template.append("# ------------------------ >8 ------------------------")
        git_template.append("# Do not modify or remove the line above.")
        git_template.append("# Everything below it will be ignored.")
        # Get the full diff
        full_diff = repo.git.diff("--cached")
        git_template.append(full_diff)

    # Combine everything
    template_text = "\n".join(git_template)
    if known.debug:
        final_text = msg + "\n\n" + stats_comment + template_text
    else:
        final_text = msg + "\n" + template_text

    # Use git's COMMIT_EDITMSG for a more authentic experience
    commit_msg_path = Path(repo.git_dir) / "COMMIT_EDITMSG"

    # Store original content
    original_content = final_text + "\n"

    # Write our message
    commit_msg_path.write_text(original_content)

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
    editor = (
        result_stdout.strip()
        if proc.returncode == 0
        else os.environ.get("EDITOR", "vi")
    )

    # Store the file's modification time before editing
    mtime_before = commit_msg_path.stat().st_mtime

    # Run the editor
    editor_proc = await asyncio.create_subprocess_shell(f"{editor} {commit_msg_path}")

    if await editor_proc.wait() != 0:
        print("error: editor exited with error code", file=sys.stderr)
        cleanup_staged_files(repo, staged_for_precommit)
        sys.exit(1)

    # Check what happened
    try:
        # Check if file was modified
        if commit_msg_path.stat().st_mtime == mtime_before:
            # File wasn't saved - user did :q! or equivalent
            print("Aborting commit due to unchanged commit message.", file=sys.stderr)
            cleanup_staged_files(repo, staged_for_precommit)
            sys.exit(1)

        final_content = commit_msg_path.read_text()
    except FileNotFoundError:
        print("Aborting commit.", file=sys.stderr)
        cleanup_staged_files(repo, staged_for_precommit)
        sys.exit(1)

    # Check for empty message (after stripping comments)
    lines = [
        line
        for line in final_content.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not lines:
        print("Aborting commit due to empty commit message.", file=sys.stderr)
        cleanup_staged_files(repo, staged_for_precommit)
        sys.exit(1)

    # Now do the actual commit with the message
    commit_proc = await asyncio.create_subprocess_exec(
        "git",
        "commit",
        "-F",
        str(commit_msg_path),
        "--no-verify",
        *passthru,
    )
    exit_code = await commit_proc.wait()

    # If we staged files temporarily and commit was cancelled/failed, unstage them
    if exit_code != 0:
        cleanup_staged_files(repo, staged_for_precommit)

    sys.exit(exit_code)


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()

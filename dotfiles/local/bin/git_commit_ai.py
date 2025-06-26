#!/usr/bin/env python3
"""
git-commit-ai

* Streams Claude (Anthropic) to draft the initial commit message shown in your editor.
* Runs the repo's pre-commit hook **in parallel** so you don't wait twice.
* Caches per-repo for one week keyed by staged diff hash.
* Limits diff context per file and prepends diffstat.

Call exactly like `git commit`; every flag is forwarded. Extra wrapper flags:

    --model MODEL          (default: sonnet)
    --debug                Enable debug logging (shows exact Claude command)

Note: --no-verify is always added internally to avoid running hooks twice. To skip
      AI message generation entirely, use regular `git commit` instead.

Important: Do NOT install this as a prepare-commit-msg hook. Since this command
         calls `git commit` internally, it would create an infinite loop. Use
         this as a standalone command replacement for `git commit`.

Example
    git-commit-ai -a               # like "git commit -a"
"""

# ---------------------------------------------------------------------
import argparse
import asyncio
import contextlib
import fcntl
import hashlib
import logging
import os
import pty
import re
import select
import shutil
import struct
import subprocess
import sys
import termios
import time
from datetime import timedelta
from enum import Enum
from pathlib import Path

from git import Repo
from rich.console import Console
from rich.text import Text

# ---------- constants -------------------------------------------------
MAX_FILE_LINES = 400  # truncate each file's hunk lines
PAST_COMMITS_MAX_CHARS = 6000  # history context ceiling
SPINNER_INTERVAL = 0.1
DEFAULT_MODEL = "sonnet"
SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def build_prompt(repo: Repo, diff: str, passthru):
    prompt = f"""Write a concise, imperative-mood Git commit message. Output ONLY the commit message between <message> and </message> tags.
No explanations, no markdown, no signatures. Do NOT include 'Generated with' or 'Co-Authored-By' lines.

Example outputs:
<message>
Add user authentication to API endpoints
</message>

<message>
Refactor database connection handling

- Extract connection pool logic into separate module
- Add retry mechanism for transient failures
</message>

Diffstat:

{diffstat(repo, passthru)}
"""

    # try to add whole staged diff
    if len(diff) < 5000:
        prompt = (
            prompt
            + f"""\nStaged diff:\

{diff}"""
        )
    else:
        prompt = (
            prompt
            + f"""\nStaged diff (first to 5000 of {len(diff)} chars)

{diff[:5000]}"""
        )

    for i, commit in enumerate(repo.iter_commits("HEAD", max_count=50)):
        new_prompt = prompt
        if i == 0:
            new_prompt += """\n\nPast commits:\n\n"""
        msg = commit.message.split("\n\n")[0]  # subject line only
        new_prompt += f"- {msg}\n"
        if len(new_prompt) > PAST_COMMITS_MAX_CHARS:
            break
        prompt = new_prompt
    return prompt


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


def diffstat(repo: Repo, passthru: list[str]) -> str:
    """Get diffstat for what would be committed."""
    if "-a" in passthru or "--all" in passthru:
        return repo.git.diff("HEAD", "--stat")
    return repo.git.diff("--cached", "--stat")


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

    def get(self, key: str) -> str | None:
        """Load a single cache entry from its file."""
        path = self.dir / f"{key}.txt"
        return path.read_text() if path.exists() else None

    def __setitem__(self, key: str, entry: str):
        """Save a single cache entry to its file."""
        path = self.dir / f"{key}.txt"
        path.write_text(entry)

    def prune(self):
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
        self._end_time = None

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
    def final_duration(self):
        """Get final duration of the task if completed, None otherwise."""
        if not self.completed:
            return None

        # Cache the duration the first time the task completes
        if self._end_time is None:
            self._end_time = time.time()

        return self._end_time - self.start_time

    def cancel(self):
        """Cancel the task."""
        if not self.task.done():
            self.task.cancel()

    @property
    def done(self):
        """Check if task is done."""
        return self.task.done()


_STATUS_ICONS: dict[TaskStatus, Text] = {
    TaskStatus.RUNNING: Text("⏳", style="yellow"),
    TaskStatus.SUCCESS: Text("✓", style="green"),
    TaskStatus.FAILED: Text("✗", style="red"),
    TaskStatus.CANCELLED: Text("-", style="dim"),
}


class ParallelTaskRunner:
    """Manages parallel execution of pre-commit and AI message generation with Rich UI."""

    def __init__(self, ai_state, precommit_state, master_fd):
        self.ai_state = ai_state
        self.precommit_state = precommit_state
        self.console = Console()
        self.start_time = time.time()
        self._status_visible = False  # Track if status line is currently visible
        self._last_status = ""  # Remember last status to clear it

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
    async def create_and_run(cls, repo, ai_task) -> str:
        """Factory method that creates runner and manages task lifecycle."""
        precommit_path = Path(repo.git_dir) / "hooks" / "pre-commit"
        master_fd, slave_fd = create_pty_with_terminal_size()

        # Check if pre-commit hook exists.
        async def run_precommit_wrapper():
            try:
                if not (precommit_path.exists() and precommit_path.is_file()):
                    return  # No pre-commit hook, nothing to do
                # Run pre-commit hook with given slave end of PTY.
                proc = await asyncio.create_subprocess_exec(
                    str(precommit_path),
                    stdout=slave_fd,
                    stderr=slave_fd,
                    stdin=slave_fd,
                    env=os.environ.copy(),
                )
                returncode = await proc.wait()
                if returncode != 0:
                    raise subprocess.CalledProcessError(returncode, str(precommit_path))
            finally:
                os.close(slave_fd)

        precommit_task = asyncio.create_task(run_precommit_wrapper())

        runner = cls(TaskState(ai_task), TaskState(precommit_task), master_fd)
        update_task = asyncio.create_task(runner._update_loop())
        output_task = asyncio.create_task(runner._stream_output(master_fd))
        try:
            # Both tasks will raise exceptions on failure
            msg, _ = await asyncio.gather(ai_task, precommit_task)
        except subprocess.CalledProcessError as e:
            # Pre-commit hook failed
            # UI will have already shown the output and status
            sys.exit(e.returncode)
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
            if not output_task.done():
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
    def elapsed(self):
        return time.time() - self.start_time

    def _status_char(self):
        if self.ai_state.done and self.precommit_state.done:
            return "✓"  # Checkmark when all done
        # Spinner
        return SPINNER_CHARS[int(self.elapsed * 10) % len(SPINNER_CHARS)]

    def _print_status_line(self):
        """Print a simple status line using carriage return."""

        # Build status with fixed widths
        parts = [
            # Status character and elapsed time (fixed width)
            f"{self._status_char()} {self.elapsed:5.1f}s",
        ]
        # Task statuses with fixed alignment
        for state, label in [
            (self.precommit_state, "pre-commit"),
            (self.ai_state, "message"),
        ]:
            duration_str = f"{state.final_duration:.1f}s" if state.completed else ""
            # Fixed width for duration
            parts.append(f"{duration_str:<5} {_STATUS_ICONS[state.status]} {label}")

        # Build status string
        status = " ".join(parts)

        # Truncate to fit terminal width
        with contextlib.suppress(Exception):
            status = status[: shutil.get_terminal_size().columns - 1]
        # Exception suppressed: If we can't get terminal size, just use full status

        # Print the status
        print(f"\r{status}", end="", flush=True)
        self._status_visible = True
        self._last_status = status

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


async def ask_claude(prompt: str, model: str) -> str:
    # Truncate prompt if too long and warn user
    if len(prompt) >= 20_000:
        truncated_prompt = prompt[:19_900] + "\n\n[TRUNCATED - prompt was too long]"
        print(
            f"# Warning: Prompt truncated from {len(prompt)} to 19,900 chars",
            file=sys.stderr,
        )
        prompt = truncated_prompt

    # Build command as list for proper handling
    cmd = [
        "claude",
        "--model",
        model,
        "-p",
        prompt,
        "--disallowedTools",
        "*",
    ]

    # Use subprocess.list2cmdline for proper shell-safe formatting
    shell_cmd = subprocess.list2cmdline(cmd)
    logger = logging.getLogger(__name__)
    logger.debug("Claude command:\n%s", shell_cmd)
    logger.debug("Prompt content:\n%s", prompt)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        # Add 30 second timeout for Claude API calls
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
    except TimeoutError:
        print("\n# Error: Claude API timed out after 30 seconds", file=sys.stderr)
        print(
            "# This might be due to network issues or API unavailability",
            file=sys.stderr,
        )
        proc.terminate()
        await proc.wait()
        raise subprocess.CalledProcessError(
            -1,
            cmd,
            "Claude command timed out after 30 seconds",
        )

    if proc.returncode != 0:
        stderr_text = stderr.decode()
        logger.debug("Claude stderr:\n%s", stderr_text)
        raise subprocess.CalledProcessError(
            proc.returncode or 1,  # Use 1 as default if returncode is None
            ["claude"],
            stderr_text,
        )

    response = stdout.decode().strip()
    logger.debug("Claude response:\n%s", response)

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


def token_estimate(text: str) -> int:
    return int(len(text) / 4)  # crude ≈4 chars / token


# ---------- main ------------------------------------------------------
def cleanup_staged_files(repo: Repo, staged_for_precommit: bool) -> None:
    """Reset staged files if they were staged temporarily for pre-commit."""
    if staged_for_precommit:
        repo.index.reset()


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
    return (
        result_stdout.strip()
        if proc.returncode == 0
        else os.environ.get("EDITOR", "vi")
    )


async def async_main():
    start = time.time()
    repo = Repo(Path.cwd(), search_parent_directories=True)

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    known, passthru = parser.parse_known_args()

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

    if known.debug:
        # Also log to stderr when debug is enabled
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(console_handler)

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

    if not (diff := get_commit_diff(repo, passthru)).strip():
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

    prompt = build_prompt(repo, diff, passthru)

    # Clean old cache entries
    cache = Cache(repo_cache_dir(repo))
    cache.prune()
    commitish = get_short_commitish(repo)
    key = f"{commitish}_{hashlib.sha256(prompt.encode()).hexdigest()}"
    if msg := cache.get(key):
        cached = True
    else:
        ai_task = asyncio.create_task(ask_claude(prompt, known.model))
        msg = await ParallelTaskRunner.create_and_run(repo, ai_task)
        cache[key] = msg
        cached = False

    elapsed = time.time() - start
    stats_comment = f"\n# ai-draft{'(cached)' if cached else ''}: prompt: {len(diff)} chars, response: {len(msg)} chars, elapsed: {elapsed:.2f}s\n"

    # Get git status information for the commit template
    branch = repo.active_branch.name if not repo.head.is_detached else "HEAD detached"
    status_output = repo.git.status("--porcelain")

    # Build the standard git commit template
    template_text = f"""# Please enter the commit message for your changes. Lines starting
# with '#' will be ignored, and an empty message aborts the commit.
#
# On branch {branch}
#
"""

    # Add list of changes to be committed
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
    untracked = [
        line[3:] for line in status_output.splitlines() if line.startswith("?? ")
    ]
    if untracked:
        template_text += """# Untracked files:
#   (use "git add <file>..." to include in what will be committed)
"""
        for filename in untracked:
            template_text += f"#\t{filename}\n"

    template_text += "#\n"

    # Add verbose diff if requested
    if "-v" in passthru or "--verbose" in passthru:
        template_text += """# ------------------------ >8 ------------------------
# Do not modify or remove the line above.
# Everything below it will be ignored.
"""
        # Get the full diff
        template_text += repo.git.diff("--cached")

    # Combine everything
    final_text = msg + stats_comment + template_text

    # Use git's COMMIT_EDITMSG for a more authentic experience
    commit_msg_path = Path(repo.git_dir) / "COMMIT_EDITMSG"
    commit_msg_path.write_text(final_text + "\n")

    # Store the file's modification time and content before editing
    mtime_before = commit_msg_path.stat().st_mtime
    content_before = final_text

    # Run the editor
    editor = await _get_editor()
    editor_proc = await asyncio.create_subprocess_shell(f"{editor} {commit_msg_path}")
    if await editor_proc.wait() != 0:
        print("error: editor exited with error code", file=sys.stderr)
        cleanup_staged_files(repo, staged_for_precommit)
        sys.exit(1)

    # Check what happened
    try:
        final_content = commit_msg_path.read_text()

        # Check if file was modified - hybrid approach
        mtime_after = commit_msg_path.stat().st_mtime
        # Compare content (strip trailing newline that gets added)
        content_after = final_content.rstrip("\n")

        if mtime_after == mtime_before and content_after == content_before:
            # File wasn't saved - user did :q! or equivalent
            print("Aborting commit due to unchanged commit message.", file=sys.stderr)
            cleanup_staged_files(repo, staged_for_precommit)
            sys.exit(1)
        elif mtime_after == mtime_before and content_after != content_before:
            # Content changed but mtime didn't - user did :wq on AI message
            # This is the desired vim workflow - proceed with commit
            pass
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

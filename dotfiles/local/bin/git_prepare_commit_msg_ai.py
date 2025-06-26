#!/usr/bin/env python3
"""
git-prepare-commit-msg AI hook

Prepends an AI-generated commit message to the commit message file.
Designed to be used as a git prepare-commit-msg hook.

Usage:
    git_prepare_commit_msg_ai.py COMMIT_MSG_FILE [SOURCE] [SHA1]

Where:
    COMMIT_MSG_FILE - The name of the file that contains the commit log message
    SOURCE - The source of the commit message (message, template, merge, squash, or commit)
    SHA1 - Commit SHA when SOURCE is commit (for -c, -C, or --amend)

The hook edits the message file in place, prepending an AI-generated message.

Installation:

Option 1: Install for a single repository
    ln -s /path/to/git_prepare_commit_msg_ai.py .git/hooks/prepare-commit-msg

Option 2: Install globally for all repositories
    git config --global core.hooksPath ~/.git-hooks
    mkdir -p ~/.git-hooks
    ln -s /path/to/git_prepare_commit_msg_ai.py ~/.git-hooks/prepare-commit-msg

Option 3: Add to existing prepare-commit-msg hook
    #!/bin/sh
    # Your existing hook logic...
    /path/to/git_prepare_commit_msg_ai.py "$@"

Configuration:
    # Set default model (optional)
    export GIT_AI_MODEL=sonnet  # or opus, haiku, etc.

    # Disable for specific commits
    git commit --no-verify  # Skips all hooks including this one

Requirements:
    - Python 3.10+
    - GitPython (pip install gitpython)
    - claude CLI tool must be in PATH
"""

import argparse
import asyncio
import hashlib
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from git import Repo

# ---------- constants -------------------------------------------------
MAX_FILE_LINES = 400  # truncate each file's hunk lines
PAST_COMMITS_MAX_CHARS = 6000  # history context ceiling
DEFAULT_MODEL = "sonnet"


def build_prompt(repo: Repo, diff: str) -> str:
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

{diffstat(repo)}
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


def get_commit_diff(repo: Repo) -> str:
    """Get the staged diff."""
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


def diffstat(repo: Repo) -> str:
    """Get diffstat for staged changes."""
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
        from datetime import timedelta

        cache_ttl = timedelta(days=7)
        now = time.time()
        for path in self.dir.glob("*.txt"):
            if now - path.stat().st_mtime > cache_ttl.total_seconds():
                path.unlink()


async def ask_claude(prompt: str, model: str) -> str:
    assert len(prompt) < 20_000  # this should be ensured by prompt builder
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
    try:
        # Add 30 second timeout for Claude API calls
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
    except asyncio.TimeoutError:
        proc.terminate()
        await proc.wait()
        raise subprocess.CalledProcessError(
            -1,
            ["claude"],
            "Claude command timed out after 30 seconds",
        )

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


async def install_hook():
    """Install this script as a prepare-commit-msg hook in the current repository."""
    try:
        repo = Repo(Path.cwd(), search_parent_directories=True)
    except Exception:
        print("Error: Not in a git repository", file=sys.stderr)
        sys.exit(1)

    hook_path = Path(repo.git_dir) / "hooks" / "prepare-commit-msg"
    script_path = Path(__file__).resolve()

    # Check if hook already exists
    if hook_path.exists():
        # Check if it's a symlink to this script
        if hook_path.is_symlink() and hook_path.resolve() == script_path:
            print("Hook already installed!")
            return

        # Check if it's the sample hook
        if hook_path.name == "prepare-commit-msg.sample" or not os.access(
            str(hook_path),
            os.X_OK,
        ):
            # It's a template/sample, safe to replace
            hook_path.unlink()
        else:
            # It's an existing executable hook
            print(
                f"Error: Existing prepare-commit-msg hook found at {hook_path}",
                file=sys.stderr,
            )
            print("To install this hook, either:", file=sys.stderr)
            print(
                "  1. Remove the existing hook and run --install again",
                file=sys.stderr,
            )
            print(
                "  2. Integrate this script into your existing hook by calling:",
                file=sys.stderr,
            )
            print(f'     {script_path} "$@"', file=sys.stderr)
            sys.exit(1)

    # Create hooks directory if it doesn't exist
    hook_path.parent.mkdir(exist_ok=True)

    # Create symlink
    hook_path.symlink_to(script_path)
    print(f"Successfully installed prepare-commit-msg hook in {repo.git_dir}/hooks/")
    print(
        "The hook will prepend AI-generated commit messages when you run 'git commit'",
    )
    print(
        f"To change the model, set GIT_AI_MODEL environment variable (current: {os.environ.get('GIT_AI_MODEL', DEFAULT_MODEL)})",
    )


async def async_main():
    start = time.time()

    # Parse arguments according to prepare-commit-msg hook interface
    parser = argparse.ArgumentParser(description="AI-powered prepare-commit-msg hook")
    parser.add_argument(
        "commit_msg_file",
        nargs="?",
        help="Path to the commit message file",
    )
    parser.add_argument(
        "source",
        nargs="?",
        default="",
        help="Source of the commit message",
    )
    parser.add_argument(
        "sha",
        nargs="?",
        default="",
        help="Commit SHA (for -c, -C, --amend)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("GIT_AI_MODEL", DEFAULT_MODEL),
        help="Model to use (default: $GIT_AI_MODEL or 'sonnet')",
    )
    parser.add_argument(
        "--disable",
        action="store_true",
        help="Disable AI message generation (for testing)",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Install this script as prepare-commit-msg hook in current repo",
    )

    args = parser.parse_args()

    # Handle installation
    if args.install:
        await install_hook()
        return

    # If installing, commit_msg_file is required
    if not args.commit_msg_file:
        parser.error("commit_msg_file is required unless using --install")

    # Skip if disabled or if message already provided
    if args.disable or args.source == "message":
        return

    # Skip for merge/squash commits
    if args.source in ["merge", "squash"]:
        return

    try:
        repo = Repo(Path.cwd(), search_parent_directories=True)
    except Exception:
        # Not in a git repository, exit silently
        return

    # Get the staged diff
    diff = get_commit_diff(repo)
    if not diff.strip():
        # No staged changes, nothing to generate message for
        return

    prompt = build_prompt(repo, diff)

    # Clean old cache entries
    cache = Cache(repo_cache_dir(repo))
    cache.prune()
    commitish = get_short_commitish(repo)
    key = f"{commitish}_{hashlib.sha256(prompt.encode()).hexdigest()}"

    if msg := cache.get(key):
        cached = True
    else:
        try:
            msg = await ask_claude(prompt, args.model)
            cache[key] = msg
            cached = False
        except Exception as e:
            # If AI generation fails, just continue without it
            print(f"# Warning: AI message generation failed: {e}", file=sys.stderr)
            return

    elapsed = time.time() - start
    stats_comment = f"\n# ai-draft{'(cached)' if cached else ''}: prompt: {len(diff)} chars, response: {len(msg)} chars, elapsed: {elapsed:.2f}s\n"

    # Read the existing commit message file
    commit_msg_path = Path(args.commit_msg_file)
    try:
        existing_content = commit_msg_path.read_text()
    except Exception:
        existing_content = ""

    # Prepend the AI message and stats comment
    new_content = msg + stats_comment + existing_content

    # Write back the modified message
    commit_msg_path.write_text(new_content)


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()

"""Git safety wrapper — blocks dangerous git operations.

Intercepts git invocations, rejects blocked patterns (git add -A, git stash,
git commit --amend), and execs the real git binary for everything else.
"""

import os
import sys
from pathlib import Path

_WRAPPER_DIR_ENV = "_GIT_WRAPPER_DIR"

# Git global options that consume the next argument as a value.
_GLOBAL_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix"})


def _resolve_real_git() -> str:
    """Find the real git binary on PATH, skipping the wrapper directory."""
    wrapper_dir = os.environ.get(_WRAPPER_DIR_ENV, "")
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if wrapper_dir and Path(directory).resolve() == Path(wrapper_dir).resolve():
            continue
        candidate = Path(directory) / "git"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise FileNotFoundError("No git found on PATH (outside wrapper directory)")


def _extract_subcommand(args: list[str]) -> tuple[str | None, list[str]]:
    """Parse git global options to find the subcommand and its arguments.

    Returns (subcommand, sub_args) or (None, []) if no subcommand found.
    """
    i = 0
    while i < len(args):
        arg = args[i]

        # --option=value form: skip (value is inline)
        if arg.startswith("--") and "=" in arg:
            opt_name = arg.split("=", 1)[0]
            if opt_name in _GLOBAL_VALUE_OPTIONS:
                i += 1
                continue

        # Value-consuming options: skip next arg too
        if arg in _GLOBAL_VALUE_OPTIONS:
            i += 2
            continue

        # Boolean flags
        if arg.startswith("-"):
            i += 1
            continue

        # First non-flag token is the subcommand
        return arg, args[i + 1 :]

    return None, []


def _check_blocked(subcommand: str, sub_args: list[str]) -> str | None:
    """Return an error message if the command is blocked, None if allowed."""
    if subcommand == "add":
        if "--all" in sub_args:
            return "git add --all\n  Use 'git add <specific-files>' instead of staging everything."
        for arg in sub_args:
            if arg == "-A":
                return "git add -A\n  Use 'git add <specific-files>' instead of staging everything."
            # Combined short flags like -Av
            if arg.startswith("-") and not arg.startswith("--") and "A" in arg:
                return f"git add {arg} (contains -A)\n  Use 'git add <specific-files>' instead of staging everything."
        if "." in sub_args:
            return "git add .\n  Use 'git add <specific-files>' instead of staging everything."

    if subcommand == "stash":
        return "git stash\n  Do not use git stash. Find other approaches for dirty worktrees."

    if subcommand == "commit" and "--amend" in sub_args:
        return "git commit --amend\n  Create a new commit instead of amending."

    return None


def main() -> None:
    args = sys.argv[1:]
    subcommand, sub_args = _extract_subcommand(args)

    if subcommand:
        error = _check_blocked(subcommand, sub_args)
        if error:
            print(f"[git-wrapper] BLOCKED: {error}", file=sys.stderr)
            raise SystemExit(1)

    real_git = _resolve_real_git()
    os.execvp(real_git, [real_git, *args])


if __name__ == "__main__":
    main()

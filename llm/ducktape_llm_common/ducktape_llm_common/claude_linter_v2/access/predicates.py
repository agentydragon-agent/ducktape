"""Built-in predicates for access control."""

from collections.abc import Callable

from .context import PredicateContext


def create_tool_predicate(tool_name: str, pattern: str | None = None) -> Callable[[PredicateContext], bool]:
    """
    Create a predicate that matches a specific tool and optionally a path pattern.

    Args:
        tool_name: Name of the tool to match
        pattern: Optional glob pattern for paths

    Returns:
        Predicate function
    """

    def predicate(ctx: PredicateContext) -> bool:
        if ctx.tool != tool_name:
            return False

        if pattern and ctx.path:
            return ctx.glob_match(pattern)

        return True

    return predicate


def safe_git_commands(ctx: PredicateContext) -> bool:
    """
    Check if a git command is safe (no force push, no hard reset, etc).

    Safe commands include:
    - status, diff, log, show
    - add, commit (without --amend)
    - checkout (files only, not branches with -b)
    - pull, fetch
    - push (without --force)
    """
    if ctx.tool != "Bash":
        return False

    if not ctx.command:
        return False

    # Must be a git command
    if not ctx.command.strip().startswith("git "):
        return False

    # Extract git subcommand
    parts = ctx.command.strip().split()
    if len(parts) < 2:
        return False

    subcommand = parts[1]

    # Always safe commands
    safe_read_commands = {
        "status",
        "diff",
        "log",
        "show",
        "branch",
        "remote",
        "describe",
        "tag",
        "ls-files",
        "grep",
        "blame",
    }
    if subcommand in safe_read_commands:
        return True

    # Conditionally safe commands
    command_str = " ".join(parts[1:])

    # Safe add/commit
    if subcommand == "add":
        return True

    if subcommand == "commit":
        # No amending
        return "--amend" not in command_str

    # Safe checkout (files only)
    if subcommand == "checkout":
        # No branch creation
        return "-b" not in command_str

    # Safe push/pull
    if subcommand in ("pull", "fetch"):
        return True

    if subcommand == "push":
        # No force push
        return "--force" not in command_str and "-f" not in command_str

    # Everything else is unsafe
    return False


def is_test_file(ctx: PredicateContext) -> bool:
    """Check if the current context is for a test file."""
    return ctx.is_test_file()


def is_prod_file(ctx: PredicateContext) -> bool:
    """Check if the current context is for a production file."""
    return ctx.is_prod_file()


def business_hours(ctx: PredicateContext) -> bool:
    """Check if current time is during business hours (9 AM - 5 PM local time)."""
    hour = ctx.timestamp.hour
    return 9 <= hour < 17


def weekday(ctx: PredicateContext) -> bool:
    """Check if current day is a weekday (Monday-Friday)."""
    # Monday = 0, Sunday = 6
    return ctx.timestamp.weekday() < 5


# Registry of built-in predicates
BUILTIN_PREDICATES: dict[str, Callable[[PredicateContext], bool]] = {
    "safe_git_commands": safe_git_commands,
    "is_test_file": is_test_file,
    "is_prod_file": is_prod_file,
    "business_hours": business_hours,
    "weekday": weekday,
}


def register_builtin(name: str, predicate: Callable[[PredicateContext], bool]) -> None:
    """Register a new built-in predicate."""
    BUILTIN_PREDICATES[name] = predicate

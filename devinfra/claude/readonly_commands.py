"""Claude Code built-in read-only command validation.

Commands that Claude Code auto-allows without any permission entry.
Source: readOnlyValidation.ts, readOnlyCommandValidation.ts in the Claude Code binary.
"""


def _skip_env_prefix(parts: list[str]) -> int:
    i = 0
    while i < len(parts) and "=" in parts[i] and not parts[i].startswith("-"):
        i += 1
    return i


# Any-args auto-allowed
_BUILTIN_CMDS = frozenset(
    [
        "cal",
        "uptime",
        "cat",
        "head",
        "tail",
        "wc",
        "stat",
        "strings",
        "hexdump",
        "od",
        "nl",
        "id",
        "uname",
        "free",
        "df",
        "du",
        "locale",
        "groups",
        "nproc",
        "basename",
        "dirname",
        "realpath",
        "cut",
        "paste",
        "tr",
        "column",
        "tac",
        "rev",
        "fold",
        "expand",
        "unexpand",
        "fmt",
        "comm",
        "cmp",
        "numfmt",
        "readlink",
        "diff",
        "true",
        "false",
        "sleep",
        "which",
        "type",
        "expr",
        "test",
        "getconf",
        "seq",
        "tsort",
        "pr",
        "echo",
        "printf",
        "ls",
        "cd",
        "find",
    ]
)

_GIT_READONLY = frozenset(
    [
        "status",
        "log",
        "diff",
        "show",
        "blame",
        "branch",
        "tag",
        "remote",
        "ls-files",
        "ls-remote",
        "config",
        "rev-parse",
        "describe",
        "reflog",
        "shortlog",
        "cat-file",
        "for-each-ref",
        "worktree",
        "name-rev",
    ]
)

_GH_READONLY = frozenset(["pr", "issue", "run", "workflow", "repo", "release", "auth", "api"])

_KUBECTL_READONLY = frozenset(
    ["get", "describe", "logs", "top", "api-resources", "api-versions", "version", "cluster-info"]
)


def is_builtin_allowed(cmd: str) -> bool:
    """Check if Claude Code auto-allows this command without any config."""
    parts = cmd.split()
    if not parts:
        return True
    i = _skip_env_prefix(parts)
    if i >= len(parts):
        return True
    first = parts[i]
    if first == "sudo":
        i += 1
        if i >= len(parts):
            return True
        first = parts[i]

    if first in _BUILTIN_CMDS:
        return True

    if first == "git" and len(parts) > i + 1:
        sub = parts[i + 1]
        if sub in _GIT_READONLY:
            return True
        if sub == "stash" and len(parts) > i + 2 and parts[i + 2] in ("list", "show"):
            return True

    if first == "gh" and len(parts) > i + 1 and parts[i + 1] in _GH_READONLY:
        return True

    return first == "kubectl" and len(parts) > i + 1 and parts[i + 1] in _KUBECTL_READONLY

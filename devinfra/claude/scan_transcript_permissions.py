"""Scan Claude Code session transcripts for permission allowlist candidates.

Usage:
    python3 devinfra/claude/scan_transcript_permissions.py [--max-sessions N] [--min-count N]
"""

import argparse
import json
from collections import Counter
from pathlib import Path

# Source: Claude Code readOnlyValidation.ts, readOnlyCommandValidation.ts
AUTO_ALLOWED_BASE = frozenset(
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

AUTO_ALLOWED_NOARGS = frozenset({"pwd", "whoami", "alias"})

GIT_READ_ONLY = frozenset(
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

GH_READ_ONLY = frozenset(["pr", "issue", "run", "workflow", "repo", "release", "auth", "api"])

KUBECTL_READ_ONLY = frozenset(
    ["get", "describe", "logs", "top", "api-resources", "api-versions", "version", "cluster-info"]
)

# From nix/home/allowed-commands.nix
NIX_ALLOWED_PREFIXES = [
    *(
        f"{exe} {sub}"
        for exe in ("bazel", "bazelisk")
        for sub in ("query", "cquery", "aquery", "info", "build", "test")
    ),
    *(
        f"nix develop --command {exe} {sub}"
        for exe in ("bazel", "bazelisk")
        for sub in ("query", "cquery", "aquery", "info", "build", "test")
    ),
    *(f"git {sub}" for sub in ("diff", "log", "show", "stash list", "stash show", "status")),
    *(f"nix {sub}" for sub in ("eval", "build", "hash", "search")),
    *(f"cargo {sub}" for sub in ("info", "search", "tree")),
    "home-manager build",
]

# From .claude/settings.json
SETTINGS_PREFIXES = [
    *(f"bb {sub}" for sub in ("remote", "build", "query", "test")),
    *(f"bbapi {sub}" for sub in ("artifact", "invocation", "target")),
    "bbr",
    "flux reconcile",
    *(f"gh pr {sub}" for sub in ("list", "view")),
    *(f"gh run {sub}" for sub in ("list", "view")),
    "gh search",
    *(
        f"kubectl get {r}"
        for r in (
            "gitrepository",
            "grafanadatasource",
            "helmrelease",
            "imagerepository",
            "job",
            "kustomization",
            "networkpolicy",
            "ns",
            "pod",
            "pods",
            "receiver",
            "svc",
            "terraform",
        )
    ),
    "kubectl rollout restart",
    "kubectl top",
    "pre-commit run",
]

# From nix/lib/inspection-commands.nix
INSPECTION_CMDS = frozenset(
    [
        "lspci",
        "lsusb",
        "lscpu",
        "lsblk",
        "sensors",
        "ps",
        "pstree",
        "top",
        "htop",
        "pgrep",
        "free",
        "vmstat",
        "df",
        "du",
        "findmnt",
        "netstat",
        "ss",
        "dig",
        "nslookup",
        "host",
        "traceroute",
        "mtr",
        "nmap",
        "lsmod",
        "dmesg",
        "journalctl",
        "last",
        "w",
        "who",
        "users",
        "id",
        "groups",
        "lpstat",
        "rfkill",
    ]
)

# Combined prefix set for fast matching
_COVERED_PREFIXES = tuple(NIX_ALLOWED_PREFIXES + SETTINGS_PREFIXES)


def _skip_env_prefix(parts: list[str]) -> int:
    """Return index past any KEY=VALUE env-var prefixes."""
    i = 0
    while i < len(parts) and "=" in parts[i] and not parts[i].startswith("-"):
        i += 1
    return i


def is_covered(cmd: str) -> bool:
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

    if first in AUTO_ALLOWED_BASE | INSPECTION_CMDS:
        return True

    if first == "git" and len(parts) > i + 1:
        sub = parts[i + 1]
        if sub in GIT_READ_ONLY:
            return True
        if sub == "stash" and len(parts) > i + 2 and parts[i + 2] in ("list", "show"):
            return True

    if first == "gh" and len(parts) > i + 1 and parts[i + 1] in GH_READ_ONLY:
        return True

    if first == "kubectl" and len(parts) > i + 1 and parts[i + 1] in KUBECTL_READ_ONLY:
        return True

    return any(cmd.startswith(p) for p in _COVERED_PREFIXES)


def extract_command_key(cmd: str) -> str | None:
    parts = cmd.split()
    if not parts:
        return None
    i = _skip_env_prefix(parts)
    if i >= len(parts):
        return None
    first = parts[i]
    if first == "sudo":
        i += 1
        if i >= len(parts):
            return None
        first = parts[i]
    if first in ("for", "if", "while", "case", "until", "do", "done", "then"):
        return None
    if len(parts) > i + 1 and not parts[i + 1].startswith("-") and parts[i + 1] not in ("|", "&&", "||", ";"):
        return f"{first} {parts[i + 1]}"
    return first


def find_transcripts(max_sessions: int = 50) -> list[Path]:
    claude_dir = Path.home() / ".claude" / "projects"
    if not claude_dir.exists():
        return []
    files = sorted(
        (p for p in claude_dir.rglob("*.jsonl") if "subagents" not in str(p)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[:max_sessions]


def _iter_tool_calls(transcripts: list[Path], tool_name: str | None = None):
    """Yield (tool_name, input_dict) for each matching tool call in transcripts."""
    for fpath in transcripts:
        try:
            with fpath.open() as fh:
                for line in fh:
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") != "assistant":
                        continue
                    content = obj.get("message", {}).get("content")
                    if not isinstance(content, list):
                        continue
                    for c in content:
                        if not isinstance(c, dict) or c.get("type") != "tool_use":
                            continue
                        name = c.get("name", "")
                        if tool_name and name != tool_name:
                            continue
                        if not tool_name and not name.startswith("Bash") and not name.startswith("mcp__"):
                            continue
                        yield name, c.get("input", {})
        except OSError:
            continue


def scan_transcripts(max_sessions: int = 50) -> tuple[Counter, Counter, Counter]:
    all_cmds: Counter = Counter()
    uncovered_cmds: Counter = Counter()
    mcp_tools: Counter = Counter()

    transcripts = find_transcripts(max_sessions)
    for name, inp in _iter_tool_calls(transcripts):
        if name == "Bash":
            cmd = inp.get("command", "").strip()
            if not cmd or cmd.startswith("#"):
                continue
            key = extract_command_key(cmd)
            if key:
                all_cmds[key] += 1
                if not is_covered(cmd):
                    uncovered_cmds[key] += 1
        elif name.startswith("mcp__"):
            mcp_tools[name] += 1

    return all_cmds, uncovered_cmds, mcp_tools


def _collect_run_targets(transcripts: list[Path], prefixes: tuple[str, ...]) -> Counter:
    targets: Counter = Counter()
    for _, inp in _iter_tool_calls(transcripts, tool_name="Bash"):
        cmd = inp.get("command", "").strip()
        for prefix in prefixes:
            if cmd.startswith(prefix):
                for part in cmd[len(prefix) :].split():
                    if part.startswith("//"):
                        targets[part] += 1
                        break
                break
    return targets


def _collect_kubectl_non_get(transcripts: list[Path]) -> Counter:
    counts: Counter = Counter()
    for _, inp in _iter_tool_calls(transcripts, tool_name="Bash"):
        cmd = inp.get("command", "").strip()
        if not cmd.startswith("kubectl "):
            continue
        parts = cmd.split()
        if len(parts) > 1 and parts[1] != "get":
            key = f"kubectl {parts[1]} {parts[2]}" if len(parts) > 2 else f"kubectl {parts[1]}"
            counts[key] += 1
    return counts


def _print_section(title: str, counts: Counter, min_count: int, limit: int = 60):
    print(f"\n=== {title} ===")
    shown = 0
    for key, cnt in counts.most_common(limit):
        if cnt < min_count:
            break
        print(f"  {cnt:5d}  {key}")
        shown += 1
    if not shown:
        print("  (none)")


def main():
    parser = argparse.ArgumentParser(description="Scan Claude Code transcripts for permission candidates")
    parser.add_argument("--max-sessions", type=int, default=50)
    parser.add_argument("--min-count", type=int, default=3)
    parser.add_argument("--all", action="store_true", help="Show all commands including covered ones")
    args = parser.parse_args()

    all_cmds, uncovered_cmds, mcp_tools = scan_transcripts(args.max_sessions)
    transcripts = find_transcripts(args.max_sessions)

    if args.all:
        print("=== ALL COMMANDS (top 60) ===")
        for key, cnt in all_cmds.most_common(60):
            tag = "" if uncovered_cmds.get(key, 0) > 0 else " [covered]"
            print(f"  {cnt:5d}  {key}{tag}")

    _print_section(f"UNCOVERED COMMANDS (min {args.min_count})", uncovered_cmds, args.min_count)
    _print_section(f"MCP TOOL USAGE (min {args.min_count})", mcp_tools, args.min_count)

    run_targets = _collect_run_targets(transcripts, ("bazelisk run ", "bb run "))
    _print_section("BAZELISK/BB RUN TARGETS", run_targets, args.min_count, 20)

    kubectl_cmds = _collect_kubectl_non_get(transcripts)
    _print_section("KUBECTL COMMANDS (non-get)", kubectl_cmds, args.min_count, 30)


if __name__ == "__main__":
    main()

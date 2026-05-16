"""Scan Claude Code session transcripts for Bash and MCP tool usage patterns.

Outputs a frequency table of command+subcommand pairs, useful for identifying
candidates for the permissions allowlist. Designed to be idempotent and
reproducible.

Usage:
    python3 devinfra/claude/scan_transcript_permissions.py [--max-sessions N] [--min-count N]
"""

import argparse
import json
from collections import Counter
from pathlib import Path

# Claude Code auto-allows these without any permission entry.
# Source: Claude Code readOnlyValidation.ts, readOnlyCommandValidation.ts
AUTO_ALLOWED_BASE = frozenset(
    {
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
    }
)

AUTO_ALLOWED_NOARGS = frozenset({"pwd", "whoami", "alias"})

GIT_READ_ONLY = frozenset(
    {
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
    }
)

GH_READ_ONLY = frozenset({"pr", "issue", "run", "workflow", "repo", "release", "auth", "api"})

KUBECTL_READ_ONLY = frozenset(
    {"get", "describe", "logs", "top", "api-resources", "api-versions", "version", "cluster-info"}
)

# Prefix patterns from allowed-commands.nix that generate Bash() permissions
NIX_ALLOWED_PREFIXES = [
    "git diff",
    "git log",
    "git show",
    "git stash list",
    "git stash show",
    "git status",
    "bazel query",
    "bazel cquery",
    "bazel aquery",
    "bazel info",
    "bazel build",
    "bazel test",
    "bazelisk query",
    "bazelisk cquery",
    "bazelisk aquery",
    "bazelisk info",
    "bazelisk build",
    "bazelisk test",
    "nix develop --command bazel query",
    "nix develop --command bazel cquery",
    "nix develop --command bazel aquery",
    "nix develop --command bazel info",
    "nix develop --command bazel build",
    "nix develop --command bazel test",
    "nix develop --command bazelisk query",
    "nix develop --command bazelisk cquery",
    "nix develop --command bazelisk aquery",
    "nix develop --command bazelisk info",
    "nix develop --command bazelisk build",
    "nix develop --command bazelisk test",
    "nix eval",
    "nix build",
    "nix hash",
    "nix search",
    "cargo info",
    "cargo search",
    "cargo tree",
    "home-manager build",
]

# Prefix patterns from project .claude/settings.json
SETTINGS_PREFIXES = [
    "bb remote",
    "bbapi artifact",
    "bbapi target",
    "bbr",
    "flux reconcile",
    "gh pr list",
    "gh pr view",
    "gh run list",
    "gh run view",
    "gh search",
    "kubectl get gitrepository",
    "kubectl get grafanadatasource",
    "kubectl get helmrelease",
    "kubectl get imagerepository",
    "kubectl get job",
    "kubectl get kustomization",
    "kubectl get networkpolicy",
    "kubectl get ns",
    "kubectl get pod",
    "kubectl get pods",
    "kubectl get receiver",
    "kubectl get svc",
    "kubectl get terraform",
    "kubectl rollout restart",
    "kubectl top",
    "pre-commit run",
]

# Inspection commands from nix/lib/inspection-commands.nix
INSPECTION_CMDS = frozenset(
    {
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
    }
)


def is_covered(cmd: str) -> bool:
    """Check if a command is already covered by existing permissions."""
    parts = cmd.split()
    if not parts:
        return True

    # Skip env var prefixes (KEY=VALUE patterns)
    i = 0
    while i < len(parts) and "=" in parts[i] and not parts[i].startswith("-"):
        i += 1
    if i >= len(parts):
        return True

    first = parts[i]

    # Skip sudo prefix
    if first == "sudo":
        i += 1
        if i >= len(parts):
            return True
        first = parts[i]

    # Auto-allowed base commands
    if first in AUTO_ALLOWED_BASE:
        return True

    # Git read-only (auto-allowed by Claude Code)
    if first == "git" and len(parts) > i + 1:
        sub = parts[i + 1]
        if sub in GIT_READ_ONLY:
            return True
        # Handle "git stash list" / "git stash show"
        if sub == "stash" and len(parts) > i + 2 and parts[i + 2] in ("list", "show"):
            return True

    # gh read-only (auto-allowed)
    if first == "gh" and len(parts) > i + 1:
        sub = parts[i + 1]
        if sub in GH_READ_ONLY:
            return True

    # kubectl read-only (auto-allowed)
    if first == "kubectl" and len(parts) > i + 1:
        sub = parts[i + 1]
        if sub in KUBECTL_READ_ONLY:
            return True

    # Check Nix-managed prefix matches
    for p in NIX_ALLOWED_PREFIXES:
        if cmd.startswith(p):
            return True

    # Check settings.json patterns
    for p in SETTINGS_PREFIXES:
        if cmd.startswith(p):
            return True

    return first in INSPECTION_CMDS


def extract_command_key(cmd: str) -> str | None:
    """Extract a normalized command key from a raw shell command."""
    parts = cmd.split()
    if not parts:
        return None

    i = 0
    while i < len(parts) and "=" in parts[i] and not parts[i].startswith("-"):
        i += 1
    if i >= len(parts):
        return None

    first = parts[i]
    if first == "sudo":
        i += 1
        if i >= len(parts):
            return None
        first = parts[i]

    # Shell control flow - skip
    if first in ("for", "if", "while", "case", "until", "do", "done", "then"):
        return None

    # Build key with first subcommand if it looks like a subcommand
    if len(parts) > i + 1 and not parts[i + 1].startswith("-") and parts[i + 1] not in ("|", "&&", "||", ";"):
        return f"{first} {parts[i + 1]}"
    return first


def find_transcripts(max_sessions: int = 50) -> list[Path]:
    """Find recent transcript files across all projects."""
    claude_dir = Path.home() / ".claude" / "projects"
    if not claude_dir.exists():
        return []

    files = []
    for jsonl in claude_dir.rglob("*.jsonl"):
        if "subagents" in str(jsonl):
            continue
        files.append(jsonl)

    # Sort by modification time, most recent first
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:max_sessions]


def scan_transcripts(max_sessions: int = 50) -> tuple[Counter, Counter, Counter]:
    """Scan transcripts and return (all_commands, uncovered_commands, mcp_tools)."""
    all_cmds = Counter()
    uncovered_cmds = Counter()
    mcp_tools = Counter()

    for fpath in find_transcripts(max_sessions):
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
                        inp = c.get("input", {})

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
        except OSError:
            continue

    return all_cmds, uncovered_cmds, mcp_tools


def main():
    parser = argparse.ArgumentParser(description="Scan Claude Code transcripts for permission candidates")
    parser.add_argument("--max-sessions", type=int, default=50, help="Number of recent sessions to scan (default: 50)")
    parser.add_argument("--min-count", type=int, default=3, help="Minimum occurrence count to report (default: 3)")
    parser.add_argument("--all", action="store_true", help="Show all commands, including already-covered ones")
    args = parser.parse_args()

    all_cmds, uncovered_cmds, mcp_tools = scan_transcripts(args.max_sessions)

    if args.all:
        print("=== ALL COMMANDS (top 60) ===")
        for key, cnt in all_cmds.most_common(60):
            covered = " [covered]" if cnt not in uncovered_cmds or uncovered_cmds.get(key, 0) == 0 else ""
            print(f"  {cnt:5d}  {key}{covered}")
        print()

    print(f"=== UNCOVERED COMMANDS (min {args.min_count} occurrences) ===")
    shown = 0
    for key, cnt in uncovered_cmds.most_common():
        if cnt < args.min_count:
            break
        print(f"  {cnt:5d}  {key}")
        shown += 1
    if shown == 0:
        print("  (none)")

    print(f"\n=== MCP TOOL USAGE (min {args.min_count} occurrences) ===")
    shown = 0
    for key, cnt in mcp_tools.most_common():
        if cnt < args.min_count:
            break
        print(f"  {cnt:5d}  {key}")
        shown += 1
    if shown == 0:
        print("  (none)")

    # Suggest specific bazelisk run targets
    print("\n=== BAZELISK RUN TARGETS ===")
    bazelisk_run_targets = Counter()
    for fpath in find_transcripts(args.max_sessions):
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
                        if c.get("name") != "Bash":
                            continue
                        cmd = c["input"].get("command", "").strip()
                        # Match both "bazelisk run //target" and "bb run ... //target"
                        for prefix in ("bazelisk run ", "bb run "):
                            if cmd.startswith(prefix):
                                rest = cmd[len(prefix) :].split()
                                # Find the // target
                                for part in rest:
                                    if part.startswith("//"):
                                        bazelisk_run_targets[part.split(" ")[0]] += 1
                                        break
                                break
        except OSError:
            continue

    for target, cnt in bazelisk_run_targets.most_common(20):
        if cnt >= args.min_count:
            print(f"  {cnt:5d}  {target}")

    print("\n=== BB RUN TARGETS ===")
    bb_run_targets = Counter()
    for fpath in find_transcripts(args.max_sessions):
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
                        if c.get("name") != "Bash":
                            continue
                        cmd = c["input"].get("command", "").strip()
                        if cmd.startswith("bb run "):
                            rest = cmd[len("bb run ") :].split()
                            for part in rest:
                                if part.startswith("//"):
                                    bb_run_targets[part.split(" ")[0]] += 1
                                    break
        except OSError:
            continue

    for target, cnt in bb_run_targets.most_common(20):
        if cnt >= args.min_count:
            print(f"  {cnt:5d}  {target}")

    print("\n=== KUBECTL COMMANDS (non-get) ===")
    kubectl_non_get = Counter()
    for fpath in find_transcripts(args.max_sessions):
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
                        if c.get("name") != "Bash":
                            continue
                        cmd = c["input"].get("command", "").strip()
                        if cmd.startswith("kubectl "):
                            parts = cmd.split()
                            if len(parts) > 1 and parts[1] != "get":
                                subcmd = parts[1]
                                key = f"kubectl {subcmd} {parts[2]}" if len(parts) > 2 else f"kubectl {subcmd}"
                                kubectl_non_get[key] += 1
        except OSError:
            continue

    for key, cnt in kubectl_non_get.most_common(30):
        if cnt >= args.min_count:
            print(f"  {cnt:5d}  {key}")


if __name__ == "__main__":
    main()

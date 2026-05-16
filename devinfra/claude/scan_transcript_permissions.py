"""Scan Claude Code session transcripts for permission allowlist candidates.

Reads user-configured permissions from settings files (project + global) so
coverage detection stays in sync automatically. Claude Code's built-in
auto-allow list is hardcoded here since it's compiled into the binary.

Usage:
    python3 devinfra/claude/scan_transcript_permissions.py [--max-sessions N] [--min-count N]
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

# ── Layer 1: Claude Code built-in auto-allow (compiled into binary) ────────
# Source: readOnlyValidation.ts, readOnlyCommandValidation.ts in Claude Code

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

# Tool-specific read-only subcommands (auto-allowed by Claude Code)
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


# ── Layer 2: User-configured permissions (from settings files) ─────────────

_BASH_PATTERN_RE = re.compile(r"^Bash\((.+?)(?::\*)?\)$")


def _load_bash_prefixes_from_settings(*paths: Path) -> list[str]:
    prefixes: list[str] = []
    for p in paths:
        try:
            data = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for entry in data.get("permissions", {}).get("allow", []):
            if not isinstance(entry, str):
                continue
            m = _BASH_PATTERN_RE.match(entry)
            if m:
                prefixes.append(m.group(1))
    return prefixes


class UserPermissions:
    """User-configured Bash() allow rules from Claude Code settings."""

    def __init__(self, project_dir: Path | None = None):
        settings_paths = [Path.home() / ".claude" / "settings.json"]
        if project_dir:
            settings_paths.append(project_dir / ".claude" / "settings.json")
        self.prefixes = _load_bash_prefixes_from_settings(*settings_paths)

    def covers(self, cmd: str) -> bool:
        return any(cmd.startswith(p) for p in self.prefixes)


# ── Shared helpers ─────────────────────────────────────────────────────────


def _skip_env_prefix(parts: list[str]) -> int:
    i = 0
    while i < len(parts) and "=" in parts[i] and not parts[i].startswith("-"):
        i += 1
    return i


# ── Transcript scanning ────────────────────────────────────────────────────


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


def scan_transcripts(transcripts: list[Path], user_perms: UserPermissions) -> tuple[Counter, Counter, Counter]:
    all_cmds: Counter = Counter()
    uncovered_cmds: Counter = Counter()
    mcp_tools: Counter = Counter()

    for name, inp in _iter_tool_calls(transcripts):
        if name == "Bash":
            cmd = inp.get("command", "").strip()
            if not cmd or cmd.startswith("#"):
                continue
            key = extract_command_key(cmd)
            if key:
                all_cmds[key] += 1
                if not is_builtin_allowed(cmd) and not user_perms.covers(cmd):
                    uncovered_cmds[key] += 1
        elif name.startswith("mcp__"):
            mcp_tools[name] += 1

    return all_cmds, uncovered_cmds, mcp_tools


# ── Specialized collectors ─────────────────────────────────────────────────


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


# ── Output ──────────────────────────────────────────────────────────────────


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

    user_perms = UserPermissions(project_dir=Path.cwd())
    transcripts = find_transcripts(args.max_sessions)
    all_cmds, uncovered_cmds, mcp_tools = scan_transcripts(transcripts, user_perms)

    print(f"Loaded {len(user_perms.prefixes)} Bash() allow rules from settings")

    if args.all:
        print("\n=== ALL COMMANDS (top 60) ===")
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

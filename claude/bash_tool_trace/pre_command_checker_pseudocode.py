#!/usr/bin/env python3
"""
Pre-command checker (pseudocode) for Claude Code Bash tool quirks.

Detects:
- Heredoc usage that will break due to injected "< /dev/null"
- Likely-broken pipelines where the last stage reads stdin (python -, node -, jq without file, awk w/o file)

Behavior:
- Build a Decision with allow / reason codes / LLM-facing message and optional explicit wrap offer
- Never silently rewrite; require explicit opt-in keyword to run any proposed transformed command
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class Analysis:
    has_heredoc: bool
    heredoc_delim: Optional[str]
    heredoc_body_span: Optional[tuple[int, int]]  # (start_idx, end_idx)
    has_pipe: bool
    last_stage: Optional[str]
    last_stage_reads_stdin: bool
    reasons: list[str]  # e.g. ["heredoc", "pipe_last_reads_stdin:jq-stdin"]


@dataclass
class Decision:
    allow: bool
    # If not allowed:
    reason_codes: list[str]
    message_to_llm: str  # human-friendly explanation with examples/fixes
    offer_explicit_wrap: Optional[str]
    offer_alt_commands: list[str]
    require_opt_in_keyword: Optional[str]


HEREDOC_RE = re.compile(r"<<\s*('?)([A-Za-z0-9_]+)\1")


def detect_heredoc(cmd: str) -> tuple[bool, Optional[str], Optional[tuple[int, int]]]:
    """Find <<'DELIM' or <<DELIM and its closing \nDELIM\n. Return (has, delim, body_span)."""
    m = HEREDOC_RE.search(cmd)
    if not m:
        return (False, None, None)
    delim = m.group(2)
    # find body start: first newline after the marker
    idx = cmd.find(m.group(0))
    after = cmd[idx + len(m.group(0)) :]
    nl = after.find("\n")
    if nl < 0:
        return (False, None, None)
    body_start = idx + len(m.group(0)) + nl + 1
    end_mark = f"\n{delim}\n"
    end = cmd.find(end_mark, body_start - 1)
    if end < 0:
        return (False, None, None)
    return (True, delim, (body_start, end + 1))


def split_last_stage(cmd: str) -> str:
    # Naive split is fine for screening; refine if needed
    return cmd.split("|")[-1].strip()


def last_stage_reads_stdin(stage: str) -> Optional[str]:
    """Return a tag for common stdin consumers, else None."""
    s = f" {stage} "  # pad for regex convenience
    if re.search(r"\spython\s+-\b", s):
        return "python-dash"
    if re.search(r"\snode\s+-\b", s):
        return "node-dash"
    if re.search(r"\sjq(\s|$)", s) and not re.search(
        r"\s(-f|\S+\.json(\.gz)?|\S+\.jsonl(\.gz)?)\b", s
    ):
        return "jq-stdin"
    # crude awk check: has awk but no obvious file operand
    if re.search(r"\sawk(\s|$)", s) and not re.search(r"\s[^-\s]\S+", s):
        return "awk-stdin"
    return None


def analyze_command(cmd: str) -> Analysis:
    has_heredoc, delim, span = detect_heredoc(cmd)
    has_pipe = "|" in cmd
    last = split_last_stage(cmd) if has_pipe else None
    stdin_tag = last_stage_reads_stdin(last) if last else None

    reasons: list[str] = []
    if has_heredoc:
        reasons.append("heredoc")
    if stdin_tag:
        reasons.append(f"pipe_last_reads_stdin:{stdin_tag}")

    return Analysis(
        has_heredoc=has_heredoc,
        heredoc_delim=delim,
        heredoc_body_span=span,
        has_pipe=has_pipe,
        last_stage=last,
        last_stage_reads_stdin=bool(stdin_tag),
        reasons=reasons,
    )


def build_wrap_with_bash_lc(cmd: str) -> str:
    """
    Build an explicit, transparent wrapper: bash -lc "<cmd>"
    Escape minimal characters; real impl should do robust quoting of \" $ ` \\ and control chars.
    """
    inner = cmd.replace("\\", "\\\\").replace('"', '\\"')
    return f'bash -lc "{inner}"'


def message_for_heredoc(cmd: str) -> Decision:
    wrapped = build_wrap_with_bash_lc(cmd)
    return Decision(
        allow=False,
        reason_codes=["heredoc"],
        message_to_llm=(
            "Your command uses a here-document, which breaks here because the CLI executes commands as "
            "eval '<cmd> < /dev/null>'. The '< /dev/null' redirection discards heredoc input.\n\n"
            "Fix options:\n"
            "1) Wrap the heredoc inside an inner shell so it is parsed from a string rather than stdin, e.g.\n"
            "   bash -lc \"python - <<'PY'\\nprint('ok')\\nPY\\n\"\n"
            "2) Avoid heredocs: use python -c '…' for short code; or write a file and run python /abs/file.py for multi-line.\n\n"
            "Reply 'wrap-ok' to run the explicit bash -lc wrapper below, or resend your command using the patterns above."
        ),
        offer_explicit_wrap=wrapped,
        offer_alt_commands=[
            "python -c \"print('ok')\"",
            "cat > ./scratch/script.py <<'PY'\nprint('ok')\nPY\npython ./scratch/script.py",
        ],
        require_opt_in_keyword="wrap-ok",
    )


def message_for_pipe_last_stdin(cmd: str, tag: str) -> Decision:
    sample: list[str] = []
    if tag == "python-dash":
        sample = ["# replace stdin with file:\npython /abs/script.py"]
    elif tag == "node-dash":
        sample = ["node /abs/script.js"]
    elif tag == "jq-stdin":
        sample = ["jq '.prog' input.json"]
    elif tag == "awk-stdin":
        sample = ["awk '{print $1}' input.txt"]

    return Decision(
        allow=False,
        reason_codes=[f"pipe_last_reads_stdin:{tag}"],
        message_to_llm=(
            "Your last pipeline stage reads stdin (e.g., 'jq' without a file, 'python -'). "
            "This environment injects '< /dev/null', so the last stage will not receive piped input.\n\n"
            "Fix options:\n"
            "- Pass an explicit file to the last stage (examples below), or\n"
            "- Restructure to avoid requiring stdin at the pipeline end."
        ),
        offer_explicit_wrap=None,  # wrapping does not restore stdin
        offer_alt_commands=sample,
        require_opt_in_keyword=None,
    )


def decide(cmd: str) -> Decision:
    a = analyze_command(cmd)
    if a.has_heredoc:
        return message_for_heredoc(cmd)
    if a.has_pipe and a.last_stage_reads_stdin:
        tag = a.reasons[-1].split(":", 1)[-1]
        return message_for_pipe_last_stdin(cmd, tag)
    return Decision(
        allow=True,
        reason_codes=[],
        message_to_llm="",
        offer_explicit_wrap=None,
        offer_alt_commands=[],
        require_opt_in_keyword=None,
    )


if __name__ == "__main__":
    # quick smoke test (manual)
    bad = "python - <<'PY'\nprint('ok')\nPY\n"
    print(decide(bad))

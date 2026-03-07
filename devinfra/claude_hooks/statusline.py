"""Claude Code status line script.

Receives JSON on stdin, outputs formatted status to stdout.
Displays session info, model, cwd, cost, and subscription quota utilization.
"""

from __future__ import annotations

import os
import sys

from devinfra.claude_hooks import statusline_models as sl
from devinfra.claude_hooks.usage_api import UsageResponse, get_cached_usage

# ANSI escapes
_DIM = "\033[2m"
_RESET = "\033[0m"


def _format_quota(usage: UsageResponse | None) -> str:
    if usage is None:
        return ""
    parts: list[str] = []
    if usage.five_hour is not None:
        parts.append(f"5h:{usage.five_hour.utilization:.0f}%")
    if usage.seven_day is not None:
        parts.append(f"7d:{usage.seven_day.utilization:.0f}%")
    if not parts:
        return ""
    return " ".join(parts)


def main() -> None:
    data = sl.Input.model_validate_json(sys.stdin.read())

    model_name = (data.model.display_name or data.model.id) if data.model else "unknown"

    cwd = ""
    if data.workspace:
        cwd = data.workspace.current_dir
    elif data.cwd:
        cwd = data.cwd

    home = os.environ.get("HOME", "")
    if home and cwd.startswith(home):
        cwd = "~" + cwd[len(home) :]

    cost = data.cost.total_cost_usd if data.cost else 0.0

    sections = [model_name, cwd, f"${cost:.2f}"]

    quota = _format_quota(get_cached_usage())
    if quota:
        sections.append(quota)

    sep = f" {_DIM}|{_RESET} "
    print(sep.join(sections))


if __name__ == "__main__":
    main()

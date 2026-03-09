"""Claude Code status line script.

Receives JSON on stdin, outputs formatted status to stdout.
Displays session info, model, cwd, cost, and subscription quota utilization.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta

from devinfra.claude_hooks.claude_api.statusline import Input
from devinfra.claude_hooks.usage_cache import CachedUsage, get_cached_usage

# ANSI escapes
_DIM = "\033[2m"
_RESET = "\033[0m"

_STALE_THRESHOLD = timedelta(seconds=10)


def _format_delta(delta: timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    if total_seconds >= 86400:
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        return f"{days}d{hours:02d}h"
    if total_seconds >= 3600:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{hours}h{minutes:02d}m"
    if total_seconds >= 60:
        return f"{total_seconds // 60}m"
    return f"{total_seconds}s"


def _format_quota(cached: CachedUsage | None, now: datetime | None = None) -> str:
    if cached is None:
        return ""
    usage = cached.usage
    if now is None:
        now = datetime.now(UTC)
    parts: list[str] = []
    if usage.five_hour is not None:
        parts.append(f"5h:{usage.five_hour.utilization:.0f}%")
    if usage.seven_day is not None:
        part = f"7d:{usage.seven_day.utilization:.0f}%"
        if usage.seven_day.resets_at is not None:
            remaining = usage.seven_day.resets_at - now
            if remaining.total_seconds() > 0:
                part += f" rst {_format_delta(remaining)}"
        parts.append(part)
    if not parts:
        return ""
    age = now - cached.fetched_at
    if age > _STALE_THRESHOLD:
        parts.append(f"({_format_delta(age)} ago)")
    return " ".join(parts)


def main() -> None:
    data = Input.model_validate_json(sys.stdin.read())

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

    # TODO: Wire up Admin API (/v1/organizations/cost_report) with a read-only
    # admin key to show current-month API cost in the statusline.
    sections = [model_name, cwd, f"${cost:.2f}"]

    quota = _format_quota(get_cached_usage())
    if quota:
        sections.append(quota)

    sep = f" {_DIM}|{_RESET} "
    print(sep.join(sections))


if __name__ == "__main__":
    main()

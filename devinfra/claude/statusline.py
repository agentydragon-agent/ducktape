"""Claude Code status line script.

Receives JSON on stdin, outputs formatted status to stdout.
Displays session info, model, cwd, cost, context window usage,
session duration, and subscription quota utilization.
"""

import os
import sys
from datetime import UTC, datetime, timedelta

from rich.console import Console
from rich.text import Text

from devinfra.claude.claude_api.statusline import ContextWindow, Input
from devinfra.claude.usage_cache import CachedUsage, get_cached_usage

_STALE_THRESHOLD = timedelta(seconds=10)
_SEP = Text(" ")


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


def _format_quota(cached: CachedUsage | None, now: datetime | None = None) -> Text | None:
    if cached is None:
        return None
    usage = cached.usage
    if now is None:
        now = datetime.now(UTC)
    parts: list[str] = []
    if usage.five_hour is not None and usage.five_hour.utilization >= 70:
        parts.append(f"5h:{usage.five_hour.utilization:.0f}%")
    if usage.seven_day is not None:
        part = f"7d:{usage.seven_day.utilization:.0f}%"
        if usage.seven_day.resets_at is not None:
            remaining = usage.seven_day.resets_at - now
            if remaining.total_seconds() > 0:
                part += f" rst {_format_delta(remaining)}"
        parts.append(part)
    if parts:
        age = now - cached.fetched_at
        if age > _STALE_THRESHOLD:
            parts.append(f"({_format_delta(age)} ago)")
    if not parts:
        return None
    return Text(" ".join(parts), style="dim")


def _format_context(ctx: ContextWindow | None) -> Text | None:
    if ctx is None or ctx.used_percentage is None:
        return None
    pct = ctx.used_percentage
    if pct >= 90:
        style = "bold red"
    elif pct >= 60:
        style = "yellow"
    else:
        style = "green"
    return Text(f"ctx:{pct:.0f}%", style=style)


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
    segments: list[Text] = [Text(f"{model_name} {cwd} ${cost:.2f}")]

    context_text = _format_context(data.context_window)
    if context_text is not None:
        segments.append(context_text)

    if data.cost and data.cost.total_duration_ms > 0:
        segments.append(Text(_format_delta(timedelta(milliseconds=data.cost.total_duration_ms))))

    quota_text = _format_quota(get_cached_usage())
    if quota_text is not None:
        segments.append(quota_text)

    console = Console(highlight=False)
    console.print(_SEP.join(segments), end="")


if __name__ == "__main__":
    main()

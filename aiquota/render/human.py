"""Human-readable CLI rendering — mirrors the GNOME extension popup bars."""

from aiquota.models import AllQuotas, ExtraUsage, ProviderQuota, QuotaWindow
from aiquota.pace import compute_pace
from aiquota.render.format import format_duration, format_pace, format_pace_forecast


def render(quotas: AllQuotas) -> str:
    return "\n".join(_render_provider(pq) for pq in quotas.providers)


def _render_provider(pq: ProviderQuota) -> str:
    if pq.error and pq.short_window is None and pq.long_window is None:
        return f"{pq.provider}: error — {pq.error}"

    lines = [_header(pq)]
    if pq.extra_usage is not None and pq.extra_usage.is_enabled:
        # In the extra-usage regime, the 5h/7d bars are noise: usage is already past
        # the prepaid cap and only the 7d reset matters (it ends the burn). Mirror
        # the GNOME popup's collapsed view here.
        if pq.long_window is not None:
            lines.append(f"  7d reset: ↻ {format_duration(pq.long_window.reset_seconds)}")
        return "\n".join(lines)
    if pq.short_window is not None:
        lines.append(_window_line("5h", pq.short_window))
    if pq.long_window is not None:
        lines.append(_window_line("7d", pq.long_window))
    if len(lines) == 1:
        lines.append("  no data")
    return "\n".join(lines)


def _header(pq: ProviderQuota) -> str:
    parts = [pq.provider]
    if pq.extra_usage is not None and pq.extra_usage.is_enabled:
        parts.append(_format_extra(pq.extra_usage))
    if pq.error is not None:
        parts.append(f"last refresh failed: {pq.error}")
    return "  ".join(parts)


def _format_extra(extra: ExtraUsage) -> str:
    # `⚡` flags "paying above subscription" — louder than just a number.
    pct = round(extra.utilization)
    return f"⚡ EXTRA ${extra.used_usd:.2f}/${extra.monthly_limit_usd:.0f} ({pct}%) — over plan"


def _window_line(label: str, w: QuotaWindow) -> str:
    used = f"{round(w.used_percent):>3d}%"
    reset = f"↻ {format_duration(w.reset_seconds)}"
    pace = compute_pace(w)
    parts = [f"{label}: {used}", reset]
    pace_str = format_pace(pace)
    if pace_str:
        parts.append(f"Δ{pace_str}")
    forecast = format_pace_forecast(pace, w.reset_seconds)
    if forecast:
        parts.append(forecast)
    return "  " + "  ".join(parts)

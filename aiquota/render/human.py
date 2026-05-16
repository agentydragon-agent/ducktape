"""Human-readable CLI rendering — mirrors the GNOME extension popup bars."""

from aiquota.models import AllQuotas, ExtraUsage, ProviderQuota, QuotaWindow
from aiquota.pace import compute_pace
from aiquota.render.format import format_duration, format_pace, format_pace_forecast

# At/above this 7d usage we treat the user as "currently burning extra" — every
# additional call exceeds the prepaid weekly cap and goes on the monthly bill.
# `extra_usage.is_enabled` only means the feature is on for the account, not
# that they're actively over plan. The monthly $ tally likewise accumulates
# across the whole billing month and isn't a "right now" signal.
_OVER_PLAN_PERCENT = 100.0


def render(quotas: AllQuotas) -> str:
    return "\n".join(_render_provider(pq) for pq in quotas.providers)


def _render_provider(pq: ProviderQuota) -> str:
    if pq.error and pq.short_window is None and pq.long_window is None:
        return f"{pq.provider}: error — {pq.error}"

    if _currently_over_plan(pq):
        # Mirror the GNOME popup's collapsed view: while burning, 5h/7d bars are
        # noise — what matters is when the 7d window resets (which ends the burn).
        lines = [f"{pq.provider}  {_format_extra_active(pq.extra_usage)}"]
        if pq.long_window is not None:
            lines.append(f"  7d reset: ↻ {format_duration(pq.long_window.reset_seconds)}")
        return "\n".join(lines)

    lines = [_header(pq)]
    if pq.short_window is not None:
        lines.append(_window_line("5h", pq.short_window))
    if pq.long_window is not None:
        lines.append(_window_line("7d", pq.long_window))
    if pq.extra_usage is not None and pq.extra_usage.used_usd > 0:
        # Informational: prepaid still has room, but the user already incurred
        # extra-usage spend earlier in the billing month. Worth surfacing so the
        # monthly bill doesn't sneak up.
        lines.append(f"  {_format_extra_informational(pq.extra_usage)}")
    if len(lines) == 1:
        lines.append("  no data")
    return "\n".join(lines)


def _currently_over_plan(pq: ProviderQuota) -> bool:
    if pq.extra_usage is None or not pq.extra_usage.is_enabled:
        return False
    return pq.long_window is not None and pq.long_window.used_percent >= _OVER_PLAN_PERCENT


def _header(pq: ProviderQuota) -> str:
    parts = [pq.provider]
    if pq.error is not None:
        parts.append(f"last refresh failed: {pq.error}")
    return "  ".join(parts)


def _format_extra_active(extra: ExtraUsage | None) -> str:
    # `⚡` flags "paying above subscription right now" — louder than just a number.
    if extra is None:
        return "⚡ OVER PLAN"
    pct = round(extra.utilization)
    return f"⚡ OVER PLAN — extra ${extra.used_usd:.2f}/${extra.monthly_limit_usd:.0f} ({pct}%) this month"


def _format_extra_informational(extra: ExtraUsage) -> str:
    pct = round(extra.utilization)
    return f"extra: ${extra.used_usd:.2f}/${extra.monthly_limit_usd:.0f} ({pct}%) spent this month"


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

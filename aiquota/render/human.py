"""Human-readable CLI rendering — mirrors the GNOME extension popup bars."""

from aiquota.models import AllQuotas, ExtraUsage, QuotaWindow
from aiquota.pace import compute_pace
from aiquota.render.format import format_duration, format_pace, format_pace_forecast
from aiquota.render.view_model import ProviderView, to_view


def render(quotas: AllQuotas) -> str:
    return "\n".join(_render_provider(pv) for pv in to_view(quotas).providers)


def _render_provider(pv: ProviderView) -> str:
    if pv.error and pv.short_window is None and pv.long_window is None:
        return f"{pv.provider}: error — {pv.error}"

    if pv.currently_over_plan:
        # Mirror the GNOME popup's collapsed view: while burning, 5h/7d bars are
        # noise — what matters is when the 7d window resets (which ends the burn).
        lines = [f"{pv.provider}  {_format_extra_active(pv.extra_usage)}"]
        if pv.long_window is not None:
            lines.append(f"  7d reset: ↻ {format_duration(pv.long_window.reset_seconds)}")
        return "\n".join(lines)

    lines = [_header(pv)]
    if pv.short_window is not None:
        lines.append(_window_line("5h", pv.short_window))
    if pv.long_window is not None:
        lines.append(_window_line("7d", pv.long_window))
    if pv.extra_status == "informational" and pv.extra_usage is not None:
        # Prepaid still has room, but the user incurred extra-usage spend earlier
        # in the billing month. Surface it so the monthly bill doesn't sneak up.
        lines.append(f"  {_format_extra_informational(pv.extra_usage)}")
    if len(lines) == 1:
        lines.append("  no data")
    return "\n".join(lines)


def _header(pv: ProviderView) -> str:
    parts = [pv.provider]
    if pv.error is not None:
        parts.append(f"last refresh failed: {pv.error}")
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

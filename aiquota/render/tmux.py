from aiquota.models import ProviderQuota, QuotaWindow
from aiquota.pace import binding_tint, compute_pace, tint_for

PROVIDER_PREFIX = {"claude": "C", "codex": "W", "zai": "Z"}

TINT_FG = {
    "cool": "blue",
    "ok": "white",
    "warn": "yellow",
    "hot": "red",
    "unknown": "white",
    "stale": "yellow",
    "error": "red",
}


def _window_tint(window: QuotaWindow | None, *, is_short: bool) -> str:
    if window is None:
        return "unknown"
    pace = compute_pace(window)
    return tint_for(pace, window.used_percent, is_short=is_short)


def render_provider(pq: ProviderQuota) -> str:
    prefix = PROVIDER_PREFIX.get(pq.provider, pq.provider[0].upper())
    if pq.error and pq.short_window is None and pq.long_window is None:
        color = TINT_FG["error"]
        return f"#[fg={color}]{prefix}:!#[default]"

    short_tint = _window_tint(pq.short_window, is_short=True)
    long_tint = _window_tint(pq.long_window, is_short=False)
    tint = binding_tint(short_tint, long_tint)
    color = TINT_FG.get(tint, "white")

    # Show the more informative window (prefer long if available)
    w = pq.long_window or pq.short_window
    if w is None:
        return f"#[fg={color}]{prefix}:?#[default]"

    pct = round(w.used_percent)
    return f"#[fg={color}]{prefix}:{pct}%#[default]"


def render(providers: list[ProviderQuota]) -> str:
    return " ".join(render_provider(pq) for pq in providers)

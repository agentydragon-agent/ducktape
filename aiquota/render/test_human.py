from datetime import UTC, datetime

import pytest_bazel
from syrupy.assertion import SnapshotAssertion

from aiquota.models import AllQuotas, ExtraUsage, ProviderQuota, QuotaWindow
from aiquota.render import human

if __name__ == "__main__":
    pytest_bazel.main()


def _quotas(*providers: ProviderQuota) -> AllQuotas:
    return AllQuotas(providers=list(providers), fetched_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC))


def test_renders_both_windows_with_reset_and_pace(snapshot: SnapshotAssertion) -> None:
    out = human.render(
        _quotas(
            ProviderQuota(
                provider="codex",
                short_window=QuotaWindow(used_percent=24, reset_seconds=3600 + 33 * 60, window_seconds=5 * 3600),
                long_window=QuotaWindow(used_percent=48, reset_seconds=5 * 86400 + 12 * 3600, window_seconds=7 * 86400),
            ),
            ProviderQuota(
                provider="zai",
                short_window=QuotaWindow(used_percent=49, reset_seconds=2 * 3600 + 45 * 60, window_seconds=5 * 3600),
                long_window=QuotaWindow(
                    used_percent=100, reset_seconds=6 * 86400 + 14 * 3600, window_seconds=7 * 86400
                ),
            ),
        )
    )
    assert out == snapshot


def test_extra_enabled_but_prepaid_has_room_shows_normal_bars(snapshot: SnapshotAssertion) -> None:
    # extra_usage.is_enabled=True just means the feature is on; non-zero
    # used_usd is *this month's* total, not "currently burning". While the 7d
    # window still has room, render the normal bars and surface the monthly
    # spend as an informational tail line so it doesn't sneak up.
    out = human.render(
        _quotas(
            ProviderQuota(
                provider="claude",
                short_window=QuotaWindow(used_percent=6, reset_seconds=2 * 3600 + 5 * 60, window_seconds=5 * 3600),
                long_window=QuotaWindow(used_percent=2, reset_seconds=4 * 86400 + 21 * 3600, window_seconds=7 * 86400),
                extra_usage=ExtraUsage(is_enabled=True, monthly_limit_usd=4600.0, used_usd=2324.85, utilization=50.54),
            )
        )
    )
    assert out == snapshot


def test_currently_over_plan_collapses_to_7d_reset_only(snapshot: SnapshotAssertion) -> None:
    # Only when the 7d window is actually maxed (>=100%) is the user paying
    # extra *right now* — then the bars are noise and the 7d reset (which
    # ends the burn) is what matters.
    out = human.render(
        _quotas(
            ProviderQuota(
                provider="claude",
                short_window=QuotaWindow(used_percent=99, reset_seconds=3600, window_seconds=5 * 3600),
                long_window=QuotaWindow(
                    used_percent=100, reset_seconds=6 * 86400 + 10 * 3600, window_seconds=7 * 86400
                ),
                extra_usage=ExtraUsage(is_enabled=True, monthly_limit_usd=4600.0, used_usd=3120.50, utilization=67.84),
            )
        )
    )
    assert out == snapshot


def test_error_only_when_no_data(snapshot: SnapshotAssertion) -> None:
    out = human.render(_quotas(ProviderQuota(provider="zai", error="no api key path configured")))
    assert out == snapshot


def test_error_after_partial_success_keeps_data(snapshot: SnapshotAssertion) -> None:
    out = human.render(
        _quotas(
            ProviderQuota(
                provider="claude",
                short_window=QuotaWindow(used_percent=20, reset_seconds=3600, window_seconds=5 * 3600),
                error="last call failed",
            )
        )
    )
    assert out == snapshot

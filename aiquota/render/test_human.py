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


def test_extra_usage_collapses_to_7d_reset_only(snapshot: SnapshotAssertion) -> None:
    # When the user is paying above subscription, the 5h/7d bars are noise —
    # only the 7d reset (which ends the burn) matters. Matches the GNOME popup.
    out = human.render(
        _quotas(
            ProviderQuota(
                provider="claude",
                short_window=QuotaWindow(used_percent=99, reset_seconds=3600, window_seconds=5 * 3600),
                long_window=QuotaWindow(used_percent=99, reset_seconds=6 * 86400 + 10 * 3600, window_seconds=7 * 86400),
                extra_usage=ExtraUsage(is_enabled=True, monthly_limit_usd=4600.0, used_usd=2324.85, utilization=50.54),
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

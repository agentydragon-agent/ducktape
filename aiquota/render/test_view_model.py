from datetime import UTC, datetime

import pytest_bazel

from aiquota.models import AllQuotas, ExtraUsage, ProviderQuota, QuotaWindow
from aiquota.render.view_model import currently_over_plan, to_view

if __name__ == "__main__":
    pytest_bazel.main()


def _pq(**kw) -> ProviderQuota:
    return ProviderQuota(provider="claude", **kw)


def test_no_extra_usage_is_not_over_plan() -> None:
    assert not currently_over_plan(_pq())


def test_feature_off_is_not_over_plan() -> None:
    # is_enabled=False (no credit card / opted out) → never over plan, no matter the 7d window.
    pq = _pq(
        long_window=QuotaWindow(used_percent=100, reset_seconds=0, window_seconds=604800),
        extra_usage=ExtraUsage(is_enabled=False, monthly_limit_usd=100, used_usd=0, utilization=0),
    )
    assert not currently_over_plan(pq)


def test_feature_on_but_prepaid_not_exhausted_is_not_over_plan() -> None:
    # The user's exact scenario: extra-usage feature on, $2324.85 spent earlier
    # this month, but the weekly quota is fresh — they are not *currently* burning.
    pq = _pq(
        short_window=QuotaWindow(used_percent=6, reset_seconds=3600, window_seconds=18000),
        long_window=QuotaWindow(used_percent=2, reset_seconds=86400, window_seconds=604800),
        extra_usage=ExtraUsage(is_enabled=True, monthly_limit_usd=4600, used_usd=2324.85, utilization=50.54),
    )
    assert not currently_over_plan(pq)


def test_prepaid_exhausted_with_feature_on_is_over_plan() -> None:
    pq = _pq(
        long_window=QuotaWindow(used_percent=100, reset_seconds=86400, window_seconds=604800),
        extra_usage=ExtraUsage(is_enabled=True, monthly_limit_usd=4600, used_usd=3120, utilization=67),
    )
    assert currently_over_plan(pq)


def test_extra_status_transitions() -> None:
    quotas = AllQuotas(
        providers=[
            # over plan
            ProviderQuota(
                provider="claude",
                long_window=QuotaWindow(used_percent=100, reset_seconds=86400, window_seconds=604800),
                extra_usage=ExtraUsage(is_enabled=True, monthly_limit_usd=100, used_usd=50, utilization=50),
            ),
            # informational: feature on, money spent this month, but prepaid has room
            ProviderQuota(
                provider="codex",
                long_window=QuotaWindow(used_percent=5, reset_seconds=86400, window_seconds=604800),
                extra_usage=ExtraUsage(is_enabled=True, monthly_limit_usd=100, used_usd=10, utilization=10),
            ),
            # none: no extra usage at all
            ProviderQuota(
                provider="zai", long_window=QuotaWindow(used_percent=5, reset_seconds=86400, window_seconds=604800)
            ),
            # none: feature on but nothing spent yet this month
            ProviderQuota(
                provider="opus",
                long_window=QuotaWindow(used_percent=5, reset_seconds=86400, window_seconds=604800),
                extra_usage=ExtraUsage(is_enabled=True, monthly_limit_usd=100, used_usd=0, utilization=0),
            ),
        ],
        fetched_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
    )
    statuses = {pv.provider: pv.extra_status for pv in to_view(quotas).providers}
    assert statuses == {"claude": "active", "codex": "informational", "zai": "none", "opus": "none"}

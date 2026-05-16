from datetime import UTC, datetime

from aiquota.models import AllQuotas, ProviderQuota, QuotaWindow

import pytest_bazel

if __name__ == "__main__":
    pytest_bazel.main()


def test_quota_window_defaults() -> None:
    w = QuotaWindow(used_percent=50.0, reset_seconds=1800.0, window_seconds=18000.0)
    assert w.used_percent == 50.0
    assert w.reset_seconds == 1800.0
    assert w.window_seconds == 18000.0


def test_provider_quota_error() -> None:
    pq = ProviderQuota(provider="test", error="something failed")
    assert pq.short_window is None
    assert pq.long_window is None
    assert pq.error == "something failed"


def test_all_quotas_roundtrip() -> None:
    quotas = AllQuotas(
        providers=[
            ProviderQuota(
                provider="claude",
                short_window=QuotaWindow(used_percent=72.0, reset_seconds=3600.0, window_seconds=18000.0),
                long_window=QuotaWindow(used_percent=45.0, reset_seconds=86400.0, window_seconds=604800.0),
            ),
        ],
        fetched_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
    )
    json_str = quotas.model_dump_json()
    restored = AllQuotas.model_validate_json(json_str)
    assert restored.providers[0].provider == "claude"
    assert restored.providers[0].short_window is not None
    assert restored.providers[0].short_window.used_percent == 72.0
    assert restored.fetched_at == quotas.fetched_at

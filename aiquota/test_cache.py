from datetime import UTC, datetime
from pathlib import Path

from aiquota.cache import QuotaCache
from aiquota.models import AllQuotas, ProviderQuota

import pytest_bazel

if __name__ == "__main__":
    pytest_bazel.main()


def test_cache_roundtrip(tmp_path: Path) -> None:
    cache = QuotaCache(path=tmp_path / "cache.json")
    quotas = AllQuotas(
        providers=[ProviderQuota(provider="test", error="none")],
        fetched_at=datetime.now(UTC),
    )
    cache.write(quotas)
    restored = cache.read()
    assert restored is not None
    assert restored.providers[0].provider == "test"


def test_cache_missing_returns_none(tmp_path: Path) -> None:
    cache = QuotaCache(path=tmp_path / "nonexistent.json")
    assert cache.read() is None


def test_cache_corrupt_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not json")
    cache = QuotaCache(path=path)
    assert cache.read() is None

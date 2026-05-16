from datetime import UTC, datetime
from pathlib import Path

from aiquota.cache import read, write
from aiquota.models import AllQuotas, ProviderQuota

import pytest_bazel

if __name__ == "__main__":
    pytest_bazel.main()


def test_cache_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    quotas = AllQuotas(
        providers=[ProviderQuota(provider="test", error="none")],
        fetched_at=datetime.now(UTC),
    )
    write(quotas, path)
    restored = read(path)
    assert restored is not None
    assert restored.providers[0].provider == "test"


def test_cache_missing_returns_none(tmp_path: Path) -> None:
    assert read(tmp_path / "nonexistent.json") is None


def test_cache_corrupt_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not json")
    assert read(path) is None

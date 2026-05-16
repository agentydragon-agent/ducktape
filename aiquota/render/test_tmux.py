import pytest_bazel

from aiquota.models import ProviderQuota, QuotaWindow
from aiquota.render.tmux import render, render_provider

if __name__ == "__main__":
    pytest_bazel.main()


def test_render_provider_with_data() -> None:
    pq = ProviderQuota(
        provider="claude", long_window=QuotaWindow(used_percent=45.0, reset_seconds=86400.0, window_seconds=604800.0)
    )
    result = render_provider(pq)
    assert "C:" in result
    assert "45%" in result
    assert "#[" in result


def test_render_provider_error_only() -> None:
    pq = ProviderQuota(provider="codex", error="no auth")
    result = render_provider(pq)
    assert "W:!" in result
    assert "red" in result


def test_render_provider_no_windows() -> None:
    pq = ProviderQuota(provider="zai")
    result = render_provider(pq)
    assert "Z:?" in result


def test_render_multiple() -> None:
    providers = [
        ProviderQuota(
            provider="claude", long_window=QuotaWindow(used_percent=50.0, reset_seconds=9000.0, window_seconds=18000.0)
        ),
        ProviderQuota(
            provider="codex", long_window=QuotaWindow(used_percent=90.0, reset_seconds=9000.0, window_seconds=18000.0)
        ),
    ]
    result = render(providers)
    assert "C:" in result
    assert "W:" in result
    assert "50%" in result
    assert "90%" in result

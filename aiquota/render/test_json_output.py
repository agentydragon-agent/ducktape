import json
from datetime import UTC, datetime

import pytest_bazel

from aiquota.models import AllQuotas, ProviderQuota, QuotaWindow
from aiquota.render.json_output import render

if __name__ == "__main__":
    pytest_bazel.main()


def test_json_output_valid(capsys) -> None:
    quotas = AllQuotas(
        providers=[
            ProviderQuota(
                provider="claude",
                short_window=QuotaWindow(used_percent=72.0, reset_seconds=3600.0, window_seconds=18000.0),
            )
        ],
        fetched_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
    )
    render(quotas)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["providers"][0]["provider"] == "claude"
    assert data["providers"][0]["short_window"]["used_percent"] == 72.0

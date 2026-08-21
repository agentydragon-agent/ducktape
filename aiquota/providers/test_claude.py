from pathlib import Path

import httpx
import pytest
import pytest_bazel
import respx

from aiquota.models import FetchSuccess
from aiquota.providers.claude import (
    TOKEN_URL,
    USAGE_URL,
    ClaudeProvider,
    ClaudeSettings,
    _spend_to_extra_spend,
    _to_success,
)
from aiquota.providers.client import provider_client
from devinfra.claude.claude_api.usage import UsageResponse

if __name__ == "__main__":
    pytest_bazel.main()


pytestmark = pytest.mark.asyncio


def test_spend_shape_drives_extra_spend() -> None:
    usage = UsageResponse.model_validate(
        {
            "spend": {
                "enabled": True,
                "limit": {"amount_minor": 250000, "currency": "USD", "exponent": 2},
                "used": {"amount_minor": 12345, "currency": "USD", "exponent": 2},
                "percent": 4.94,
                "severity": "normal",
            }
        }
    )
    extra = _spend_to_extra_spend(usage.spend)
    assert extra is not None
    assert extra.monthly_limit_usd == 2500.0
    assert extra.used_usd == 123.45
    assert extra.utilization == 4.94


def test_disabled_spend_does_not_render_extra_spend() -> None:
    usage = UsageResponse.model_validate({"spend": {"enabled": False, "disabled_reason": "payment_method_required"}})
    assert _spend_to_extra_spend(usage.spend) is None


def test_raw_usage_fixture_preserves_provider_windows() -> None:
    usage = UsageResponse.model_validate_json((Path(__file__).parent / "fixtures" / "claude_usage.json").read_text())

    result = _to_success(usage)

    assert [(window.window_seconds, window.used_percent) for window in result.windows] == [
        (5 * 3600, 73),
        (7 * 86400, 75),
    ]


async def test_explicit_token_is_read_only_and_never_refreshed(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    path.write_text('{"claudeAiOauth":{"accessToken":"expired", "refreshToken":"refresh", "expiresAt":0}}')
    provider = ClaudeProvider(ClaudeSettings(credentials_path=path, access_token="placeholder"), provider_client())

    with respx.mock(assert_all_called=False) as mock:
        post_route = mock.post(TOKEN_URL).mock(side_effect=AssertionError("read-only provider must not refresh"))
        usage_route = mock.get(USAGE_URL).mock(
            return_value=httpx.Response(
                200, json={"five_hour": {"utilization": 10, "resets_at": "2026-08-20T05:00:00Z"}}
            )
        )
        output = await provider.fetch()

    assert isinstance(output.result, FetchSuccess)
    assert post_route.call_count == 0
    assert usage_route.calls.last.request.headers["Authorization"] == "Bearer placeholder"
    assert "placeholder" not in path.read_text()

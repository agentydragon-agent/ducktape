"""Tests for statusline models, usage API client, and output formatting."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_bazel

from devinfra.claude.claude_api.credentials import read_access_token
from devinfra.claude.claude_api.statusline import ContextWindow, Input
from devinfra.claude.claude_api.usage import UsageBucket, UsageResponse
from devinfra.claude.statusline import _format_context, _format_quota
from devinfra.claude.usage_cache import CACHE_TTL, CachedUsage, get_cached_usage

# === statusline_models tests ===


FULL_INPUT_JSON = json.dumps(
    {
        "cwd": "/home/user/code",
        "session_id": "abc12345xyz",
        "transcript_path": "/tmp/transcript.jsonl",
        "model": {"id": "claude-opus-4-6", "display_name": "Opus"},
        "workspace": {"current_dir": "/home/user/code", "project_dir": "/home/user/code"},
        "version": "1.0.80",
        "output_style": {"name": "default"},
        "cost": {
            "total_cost_usd": 0.12,
            "total_duration_ms": 45000,
            "total_api_duration_ms": 2300,
            "total_lines_added": 156,
            "total_lines_removed": 23,
        },
        "context_window": {
            "total_input_tokens": 15234,
            "total_output_tokens": 4521,
            "context_window_size": 200000,
            "used_percentage": 8,
            "remaining_percentage": 92,
            "current_usage": {
                "input_tokens": 8500,
                "output_tokens": 1200,
                "cache_creation_input_tokens": 5000,
                "cache_read_input_tokens": 2000,
            },
        },
        "exceeds_200k_tokens": False,
        "vim": {"mode": "NORMAL"},
        "agent": {"name": "test-agent"},
    }
)


def test_parse_full_input():
    data = Input.model_validate_json(FULL_INPUT_JSON)
    assert data.session_id == "abc12345xyz"
    assert data.model is not None
    assert data.model.display_name == "Opus"
    assert data.model.id == "claude-opus-4-6"
    assert data.workspace is not None
    assert data.workspace.current_dir == "/home/user/code"
    assert data.cost is not None
    assert data.cost.total_cost_usd == 0.12
    assert data.context_window is not None
    assert data.context_window.used_percentage == 8
    assert data.context_window.current_usage is not None
    assert data.context_window.current_usage.input_tokens == 8500
    assert data.vim is not None
    assert data.vim.mode == "NORMAL"
    assert data.agent is not None
    assert data.agent.name == "test-agent"


def test_parse_minimal_input():
    data = Input.model_validate_json("{}")
    assert data.session_id == ""
    assert data.model is None
    assert data.cost is None


def test_extra_fields_ignored():
    raw = json.dumps({"session_id": "abc", "some_future_field": True, "nested": {"x": 1}})
    data = Input.model_validate_json(raw)
    assert data.session_id == "abc"


def test_null_context_usage():
    raw = json.dumps({"context_window": {"used_percentage": None, "remaining_percentage": None, "current_usage": None}})
    data = Input.model_validate_json(raw)
    assert data.context_window is not None
    assert data.context_window.used_percentage is None
    assert data.context_window.current_usage is None


# === usage_cache tests ===


def test_usage_response_parsing():
    raw = {
        "five_hour": {"utilization": 6.0, "resets_at": "2026-02-25T05:00:00+00:00"},
        "seven_day": {"utilization": 35.0, "resets_at": "2026-02-28T04:00:00+00:00"},
        "seven_day_opus": None,
        "seven_day_sonnet": {"utilization": 3.0, "resets_at": "2026-03-01T00:00:00+00:00"},
    }
    resp = UsageResponse.model_validate(raw)
    assert resp.five_hour is not None
    assert resp.five_hour.utilization == 6.0
    assert resp.seven_day is not None
    assert resp.seven_day.utilization == 35.0
    assert resp.seven_day_opus is None
    assert resp.seven_day_sonnet is not None


def test_usage_response_extra_fields():
    raw = {"five_hour": {"utilization": 10.0}, "unknown_bucket": {"utilization": 99.0}}
    resp = UsageResponse.model_validate(raw)
    assert resp.five_hour is not None
    assert resp.five_hour.utilization == 10.0


def test_read_access_token(tmp_path: Path):
    creds = {"claudeAiOauth": {"accessToken": "test-token-123"}}
    creds_file = tmp_path / ".credentials.json"
    creds_file.write_text(json.dumps(creds))

    with patch("devinfra.claude.claude_api.credentials.CREDENTIALS_PATH", creds_file):
        assert read_access_token() == "test-token-123"


def test_read_access_token_missing_file(tmp_path: Path):
    with patch("devinfra.claude.claude_api.credentials.CREDENTIALS_PATH", tmp_path / "nonexistent"):
        assert read_access_token() is None


def test_read_access_token_malformed(tmp_path: Path):
    creds_file = tmp_path / ".credentials.json"
    creds_file.write_text("not json")

    with patch("devinfra.claude.claude_api.credentials.CREDENTIALS_PATH", creds_file):
        assert read_access_token() is None


def test_get_cached_usage_fresh_cache(tmp_path: Path):
    cache_file = tmp_path / "usage_cache.json"
    usage = UsageResponse(five_hour=UsageBucket(utilization=12.0), seven_day=UsageBucket(utilization=45.0))
    cached = CachedUsage(fetched_at=datetime.now(UTC), usage=usage)
    cache_file.write_text(cached.model_dump_json())

    with patch("devinfra.claude.usage_cache.CACHE_PATH", cache_file):
        result = get_cached_usage()

    assert result is not None
    assert result.usage.five_hour is not None
    assert result.usage.five_hour.utilization == 12.0


def test_get_cached_usage_stale_cache_no_token(tmp_path: Path, no_credentials):
    cache_file = tmp_path / "usage_cache.json"
    usage = UsageResponse(five_hour=UsageBucket(utilization=99.0))
    stale_time = datetime.now(UTC) - CACHE_TTL - timedelta(seconds=10)
    cached = CachedUsage(fetched_at=stale_time, usage=usage)
    cache_file.write_text(cached.model_dump_json())

    with patch("devinfra.claude.usage_cache.CACHE_PATH", cache_file):
        result = get_cached_usage()

    # Falls back to stale cache
    assert result is not None
    assert result.usage.five_hour is not None
    assert result.usage.five_hour.utilization == 99.0


def test_get_cached_usage_no_cache_no_token(no_usage_cache, no_credentials):
    assert get_cached_usage() is None


# === statusline output tests ===


def _make_cached(usage: UsageResponse, age: timedelta = timedelta(seconds=0)) -> CachedUsage:
    return CachedUsage(fetched_at=datetime.now(UTC) - age, usage=usage)


def test_format_quota_none():
    assert _format_quota(None) is None


def test_format_quota_empty_response():
    cached = _make_cached(UsageResponse())
    assert _format_quota(cached) is None


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        pytest.param(
            UsageResponse(five_hour=UsageBucket(utilization=80.0), seven_day=UsageBucket(utilization=35.0)),
            "5h:80% 7d:35%",
            id="both_buckets",
        ),
        pytest.param(
            UsageResponse(five_hour=UsageBucket(utilization=6.0), seven_day=UsageBucket(utilization=35.0)),
            "7d:35%",
            id="five_hour_below_70_hidden",
        ),
        pytest.param(UsageResponse(five_hour=UsageBucket(utilization=85.0)), "5h:85%", id="five_hour_only_high"),
    ],
)
def test_format_quota_buckets(usage: UsageResponse, expected: str):
    now = datetime.now(UTC)
    cached = CachedUsage(fetched_at=now, usage=usage)
    result = _format_quota(cached, now=now)
    assert result is not None
    assert result.plain == expected


def test_format_quota_five_hour_low_hidden():
    now = datetime.now(UTC)
    cached = CachedUsage(fetched_at=now, usage=UsageResponse(five_hour=UsageBucket(utilization=12.5)))
    assert _format_quota(cached, now=now) is None


@pytest.mark.parametrize(
    ("age", "expected_suffix"),
    [
        pytest.param(timedelta(seconds=5), None, id="fresh"),
        pytest.param(timedelta(seconds=42), "(42s ago)", id="seconds"),
        pytest.param(timedelta(seconds=150), "(2m ago)", id="minutes"),
        pytest.param(timedelta(hours=1, minutes=5), "(1h05m ago)", id="hours"),
    ],
)
def test_format_quota_staleness(age: timedelta, expected_suffix: str | None):
    now = datetime.now(UTC)
    cached = CachedUsage(fetched_at=now - age, usage=UsageResponse(seven_day=UsageBucket(utilization=20.0)))
    result = _format_quota(cached, now=now)
    assert result is not None
    if expected_suffix is None:
        assert result.plain == "7d:20%"
    else:
        assert result.plain == f"7d:20% {expected_suffix}"


@pytest.mark.parametrize(
    ("resets_in", "expected_part"),
    [
        pytest.param(timedelta(hours=2, minutes=13), "7d:35% rst 2h13m", id="hours"),
        pytest.param(timedelta(minutes=45), "7d:35% rst 45m", id="minutes"),
        pytest.param(timedelta(days=3, hours=5), "7d:35% rst 3d05h", id="days"),
        pytest.param(timedelta(minutes=-5), "7d:35%", id="past_no_reset"),
    ],
)
def test_format_quota_seven_day_reset(resets_in: timedelta, expected_part: str):
    now = datetime.now(UTC)
    resets_at = now + resets_in
    cached = CachedUsage(
        fetched_at=now, usage=UsageResponse(seven_day=UsageBucket(utilization=35.0, resets_at=resets_at))
    )
    result = _format_quota(cached, now=now)
    assert result is not None
    assert result.plain == expected_part


# === context window tests ===


def test_format_context_none():
    assert _format_context(None) is None


def test_format_context_no_percentage():
    ctx = ContextWindow(used_percentage=None)
    assert _format_context(ctx) is None


@pytest.mark.parametrize(
    ("pct", "expected_text", "expected_style"),
    [
        pytest.param(8, "ctx:8%", "green", id="low"),
        pytest.param(42, "ctx:42%", "green", id="mid_green"),
        pytest.param(59.9, "ctx:60%", "green", id="boundary_green"),
        pytest.param(60, "ctx:60%", "yellow", id="boundary_yellow"),
        pytest.param(75, "ctx:75%", "yellow", id="mid_yellow"),
        pytest.param(89.9, "ctx:90%", "yellow", id="boundary_yellow_high"),
        pytest.param(90, "ctx:90%", "bold red", id="boundary_red"),
        pytest.param(99, "ctx:99%", "bold red", id="high_red"),
    ],
)
def test_format_context_colors(pct: float, expected_text: str, expected_style: str):
    ctx = ContextWindow(used_percentage=pct)
    result = _format_context(ctx)
    assert result is not None
    assert result.plain == expected_text
    assert result.style == expected_style


if __name__ == "__main__":
    pytest_bazel.main()

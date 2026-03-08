"""Tests for statusline models, usage API client, and output formatting."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest_bazel

from devinfra.claude_hooks.claude_api.credentials import read_access_token
from devinfra.claude_hooks.claude_api.statusline import Input
from devinfra.claude_hooks.claude_api.usage import UsageBucket, UsageResponse
from devinfra.claude_hooks.statusline import _format_quota
from devinfra.claude_hooks.usage_cache import CACHE_TTL_SECONDS, _CachedUsage, get_cached_usage

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

    with patch("devinfra.claude_hooks.claude_api.credentials.CREDENTIALS_PATH", creds_file):
        assert read_access_token() == "test-token-123"


def test_read_access_token_missing_file(tmp_path: Path):
    with patch("devinfra.claude_hooks.claude_api.credentials.CREDENTIALS_PATH", tmp_path / "nonexistent"):
        assert read_access_token() is None


def test_read_access_token_malformed(tmp_path: Path):
    creds_file = tmp_path / ".credentials.json"
    creds_file.write_text("not json")

    with patch("devinfra.claude_hooks.claude_api.credentials.CREDENTIALS_PATH", creds_file):
        assert read_access_token() is None


def test_get_cached_usage_fresh_cache(tmp_path: Path):
    cache_file = tmp_path / "usage_cache.json"
    usage = UsageResponse(five_hour=UsageBucket(utilization=12.0), seven_day=UsageBucket(utilization=45.0))
    cached = _CachedUsage(fetched_at=time.time(), usage=usage)
    cache_file.write_text(cached.model_dump_json())

    with patch("devinfra.claude_hooks.usage_cache.CACHE_PATH", cache_file):
        result = get_cached_usage()

    assert result is not None
    assert result.five_hour is not None
    assert result.five_hour.utilization == 12.0


def test_get_cached_usage_stale_cache_no_token(tmp_path: Path):
    cache_file = tmp_path / "usage_cache.json"
    usage = UsageResponse(five_hour=UsageBucket(utilization=99.0))
    stale_time = time.time() - CACHE_TTL_SECONDS - 10
    cached = _CachedUsage(fetched_at=stale_time, usage=usage)
    cache_file.write_text(cached.model_dump_json())

    creds_file = tmp_path / "nonexistent"

    with (
        patch("devinfra.claude_hooks.usage_cache.CACHE_PATH", cache_file),
        patch("devinfra.claude_hooks.claude_api.credentials.CREDENTIALS_PATH", creds_file),
    ):
        result = get_cached_usage()

    # Falls back to stale cache
    assert result is not None
    assert result.five_hour is not None
    assert result.five_hour.utilization == 99.0


def test_get_cached_usage_no_cache_no_token(tmp_path: Path):
    with (
        patch("devinfra.claude_hooks.usage_cache.CACHE_PATH", tmp_path / "nonexistent"),
        patch("devinfra.claude_hooks.claude_api.credentials.CREDENTIALS_PATH", tmp_path / "also_nonexistent"),
    ):
        result = get_cached_usage()

    assert result is None


# === statusline output tests ===


def test_format_quota_with_data():
    usage = UsageResponse(five_hour=UsageBucket(utilization=6.0), seven_day=UsageBucket(utilization=35.0))
    assert _format_quota(usage) == "5h:6% 7d:35%"


def test_format_quota_none():
    assert _format_quota(None) == ""


def test_format_quota_partial():
    usage = UsageResponse(five_hour=UsageBucket(utilization=12.5))
    assert _format_quota(usage) == "5h:12%"


def test_format_quota_empty_response():
    usage = UsageResponse()
    assert _format_quota(usage) == ""


if __name__ == "__main__":
    pytest_bazel.main()

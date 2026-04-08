from __future__ import annotations

import uuid
from unittest.mock import patch

import httpx
import pytest
import pytest_bazel

from devinfra.precommit.test_tag import (
    BuildBuddyInvocation,
    Invocations,
    LocalInvocation,
    NoTests,
    TestTagError,
    check_commit_message,
    is_exempt,
    parse_test_tag,
    verify_invocations_on_buildbuddy,
)

_UUID_STR = "abc12345-1234-5678-9abc-def012345678"
_UUID_STR_2 = "11111111-2222-3333-4444-555555555555"
_UUID = uuid.UUID(_UUID_STR)
_UUID_2 = uuid.UUID(_UUID_STR_2)


class TestIsExempt:
    @pytest.mark.parametrize(
        "message", ["Merge branch 'feature' into main", "fixup! Add new feature", "squash! Add new feature"]
    )
    def test_exempt(self, message):
        assert is_exempt(message)

    def test_normal_commit(self):
        assert not is_exempt("Add new feature")


class TestParseTestTag:
    @pytest.mark.parametrize(
        ("tag_value", "expected"),
        [
            (f"buildbuddy:{_UUID_STR}", Invocations([BuildBuddyInvocation(_UUID)])),
            (f"local:{_UUID_STR}", Invocations([LocalInvocation(_UUID)])),
            (
                f"buildbuddy:{_UUID_STR},local:{_UUID_STR_2}",
                Invocations([BuildBuddyInvocation(_UUID), LocalInvocation(_UUID_2)]),
            ),
            ("none: docs only", NoTests("docs only")),
        ],
    )
    def test_valid(self, tag_value, expected):
        assert parse_test_tag(f"Title\n\nBAZEL_TEST_INVOCATIONS={tag_value}") == expected

    def test_in_middle_of_body(self):
        msg = f"Title\n\nSome context.\nBAZEL_TEST_INVOCATIONS=buildbuddy:{_UUID_STR}\nMore text."
        assert parse_test_tag(msg) == Invocations([BuildBuddyInvocation(_UUID)])

    @pytest.mark.parametrize(
        ("tag_value", "match"),
        [
            ("", "empty"),
            ("none:", "explanation"),
            ("none:   ", "explanation"),
            (_UUID_STR, "Invalid invocation reference"),
            (f"gitlab:{_UUID_STR}", "Unknown invocation source"),
            ("buildbuddy:not-a-uuid", "Invalid UUID"),
        ],
    )
    def test_invalid(self, tag_value, match):
        with pytest.raises(TestTagError, match=match):
            parse_test_tag(f"Title\n\nBAZEL_TEST_INVOCATIONS={tag_value}")

    def test_missing(self):
        with pytest.raises(TestTagError):
            parse_test_tag("Add feature\n\nSome body")


class TestCheckCommitMessage:
    @pytest.mark.parametrize(
        "message",
        [
            f"Add feature\n\nBAZEL_TEST_INVOCATIONS=buildbuddy:{_UUID_STR}",
            f"Add feature\n\nBAZEL_TEST_INVOCATIONS=local:{_UUID_STR}",
            "Fix typo\n\nBAZEL_TEST_INVOCATIONS=none: docs only",
            "Merge branch 'feature' into main",
            "fixup! Add feature",
        ],
    )
    def test_passes(self, message):
        check_commit_message(message)

    @pytest.mark.parametrize("message", ["Add feature\n\nSome body", "Fix typo\n\nBAZEL_TEST_INVOCATIONS=none:"])
    def test_raises(self, message):
        with pytest.raises(TestTagError):
            check_commit_message(message)


class TestVerifyInvocations:
    def test_valid_test_invocation(self, monkeypatch):
        monkeypatch.setenv("BUILDBUDDY_API_KEY", "test-key")
        mock_response = httpx.Response(200, json={"invocation": [{"invocationId": _UUID_STR, "command": "test"}]})
        with patch("httpx.post", return_value=mock_response):
            verify_invocations_on_buildbuddy([_UUID])

    def test_build_invocation_rejected(self, monkeypatch):
        monkeypatch.setenv("BUILDBUDDY_API_KEY", "test-key")
        mock_response = httpx.Response(200, json={"invocation": [{"invocationId": _UUID_STR, "command": "build"}]})
        with (
            patch("httpx.post", return_value=mock_response),
            pytest.raises(TestTagError, match="'build' invocation, not 'test'"),
        ):
            verify_invocations_on_buildbuddy([_UUID])

    def test_unknown_invocation_raises(self, monkeypatch):
        monkeypatch.setenv("BUILDBUDDY_API_KEY", "test-key")
        mock_response = httpx.Response(200, json={"invocation": []})
        with patch("httpx.post", return_value=mock_response), pytest.raises(TestTagError, match="not found"):
            verify_invocations_on_buildbuddy([_UUID])

    def test_no_api_key_skips(self, monkeypatch):
        monkeypatch.delenv("BUILDBUDDY_API_KEY", raising=False)
        verify_invocations_on_buildbuddy([_UUID])

    def test_network_error_raises(self, monkeypatch):
        monkeypatch.setenv("BUILDBUDDY_API_KEY", "test-key")
        with (
            patch("httpx.post", side_effect=httpx.ConnectError("connection refused")),
            pytest.raises(TestTagError, match="connection refused"),
        ):
            verify_invocations_on_buildbuddy([_UUID])

    def test_http_error_raises(self, monkeypatch):
        monkeypatch.setenv("BUILDBUDDY_API_KEY", "test-key")
        mock_response = httpx.Response(500, text="internal server error")
        with patch("httpx.post", return_value=mock_response), pytest.raises(TestTagError, match="500"):
            verify_invocations_on_buildbuddy([_UUID])


if __name__ == "__main__":
    pytest_bazel.main()

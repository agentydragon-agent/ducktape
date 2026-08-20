import asyncio
from typing import cast

import pytest
import pytest_bazel

from haku.console.x.codex_app_server.capture import Capture, Sanitizer
from haku.console.x.codex_app_server.protocol import Direction


def test_sanitizer_never_serializes_credentials_environment_paths_or_native_ids():
    sanitizer = Sanitizer(
        workspace="/private/workspace", prompt="say the fixed phrase", environment_values=("environment-secret-value",)
    )
    sanitized = sanitizer.sanitize(
        {
            "authorization": "Bearer credential",
            "cookie": "session=credential-cookie",
            "github_token": "plain-token-value",
            "cwd": "/private/workspace",
            "params": {
                "threadId": "019-native-thread",
                "turnId": "019-native-turn",
                "itemId": "native-item",
                "delta": (
                    "say the fixed phrase environment-secret-value /home/person/file sk-secretvalue123456 "
                    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature12345 "
                    "https://example.invalid/path?X-Amz-Signature=query-secret"
                ),
            },
        }
    )

    encoded = repr(sanitized)
    assert "credential" not in encoded
    assert "plain-token-value" not in encoded
    assert "query-secret" not in encoded
    assert "signature12345" not in encoded
    assert "environment-secret-value" not in encoded
    assert "/private/workspace" not in encoded
    assert "/home/person" not in encoded
    assert "native-thread" not in encoded
    assert "native-turn" not in encoded
    assert "native-item" not in encoded
    assert sanitized["params"]["threadId"] == "<THREAD_1>"
    assert sanitized["params"]["turnId"] == "<TURN_1>"
    assert sanitized["params"]["itemId"] == "<ITEM_1>"
    assert "<PROMPT>" in sanitized["params"]["delta"]


def test_capture_refuses_to_write_past_the_total_byte_budget(tmp_path):
    output = tmp_path / "capture.jsonl"
    output.write_text("")
    capture = Capture(
        process=cast(asyncio.subprocess.Process, None),
        output=output,
        sanitizer=Sanitizer(workspace="/workspace", prompt="prompt", environment_values=()),
        timeout_seconds=1,
        max_messages=10,
        max_bytes=20,
    )

    with pytest.raises(RuntimeError, match=r"capture exceeded --max-bytes=20"):
        capture._record(Direction.SERVER_TO_CLIENT, {"method": "notification", "params": {}})

    assert output.read_text() == ""
    assert capture.messages == 0
    assert capture.bytes_written == 0


if __name__ == "__main__":
    pytest_bazel.main()

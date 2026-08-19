import pytest_bazel

from haku.console.x.codex_app_server.capture import Sanitizer


def test_sanitizer_never_serializes_credentials_environment_paths_or_native_ids():
    sanitizer = Sanitizer(
        workspace="/private/workspace", prompt="say the fixed phrase", environment_values=("environment-secret-value",)
    )
    sanitized = sanitizer.sanitize(
        {
            "authorization": "Bearer credential",
            "cwd": "/private/workspace",
            "params": {
                "threadId": "019-native-thread",
                "turnId": "019-native-turn",
                "itemId": "native-item",
                "delta": "say the fixed phrase environment-secret-value /home/person/file sk-secretvalue123456",
            },
        }
    )

    encoded = repr(sanitized)
    assert "credential" not in encoded
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


if __name__ == "__main__":
    pytest_bazel.main()

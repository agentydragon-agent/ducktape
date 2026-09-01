import json
from pathlib import Path

import pytest
import pytest_bazel

from x.agentplane.capture.framing import NewlineFramer
from x.agentplane.capture.providers.shared_capture import NativeCapture


def test_framer_preserves_crlf_and_eof_tail() -> None:
    framer = NewlineFramer()
    assert framer.feed(b'{"a":') == []
    assert framer.feed(b"null}\r\nmalformed") == [(b'{"a":null}', b"\r\n", False)]
    assert framer.finish() == [(b"malformed", b"", True)]


def test_invalid_native_stdout_is_not_ignored(tmp_path: Path) -> None:
    capture = NativeCapture(tmp_path, [], cwd=tmp_path, environment={})
    capture.frames.put("not-json")
    with pytest.raises(json.JSONDecodeError):
        capture.await_frame(lambda _frame: True, timeout=0.1)


if __name__ == "__main__":
    pytest_bazel.main()

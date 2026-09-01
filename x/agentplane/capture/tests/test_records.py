import base64

import pytest_bazel

from x.agentplane.capture.framing import NewlineFramer
from x.agentplane.capture.providers.shared_capture import raw


def test_framer_preserves_crlf_and_eof_tail() -> None:
    framer = NewlineFramer()
    assert framer.feed(b'{"a":') == []
    assert framer.feed(b"null}\r\nmalformed") == [(b'{"a":null}', b"\r\n", False)]
    assert framer.finish() == [(b"malformed", b"", True)]


def test_raw_example_is_decodable_and_optional_json_is_diagnostic() -> None:
    record = raw(b'{"value":null}')
    assert base64.b64decode(record["base64"], validate=True) == b'{"value":null}'
    assert record["json"] == {"value": None}


if __name__ == "__main__":
    pytest_bazel.main()

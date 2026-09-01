import pytest_bazel

from x.agentplane.capture.framing import NewlineFramer
from x.agentplane.capture.providers.shared_capture import text, text_record


def test_framer_preserves_crlf_and_eof_tail() -> None:
    framer = NewlineFramer()
    assert framer.feed(b'{"a":') == []
    assert framer.feed(b"null}\r\nmalformed") == [(b'{"a":null}', b"\r\n", False)]
    assert framer.finish() == [(b"malformed", b"", True)]


def test_text_evidence_needs_no_base64_or_parsed_json_copy() -> None:
    assert text(b'{"value":null}') == '{"value":null}'
    record = text_record(b'{"value":null}')
    assert record["text"] == '{"value":null}'
    assert "base64" not in record
    assert "json" not in record


if __name__ == "__main__":
    pytest_bazel.main()

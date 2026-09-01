from x.agentplane.capture.framing import NewlineFramer
from x.agentplane.capture.records import RawRecord, decode_b64, json_wrapper


def test_json_null_has_present_wrapper() -> None:
    assert json_wrapper(b"null") == {"state": "parsed", "value": None}


def test_framer_preserves_crlf_and_eof_tail() -> None:
    framer = NewlineFramer()
    assert framer.feed(b'{"a":') == []
    assert framer.feed(b"null}\r\nmalformed") == [(b'{"a":null}', b"\r\n", False)]
    assert framer.finish() == [(b"malformed", b"", True)]


def test_raw_record_round_trips_authoritative_bytes() -> None:
    record = RawRecord(b'{"value":null}', 1, 1, "harness_stdout", 2, b"\n")
    payload = record.as_dict(wall_time="2026-01-01T00:00:00Z", monotonic_ns=1)
    assert decode_b64(payload["raw_base64"]) == b'{"value":null}'
    assert payload["parsed"] == {"state": "parsed", "value": {"value": None}}


if __name__ == "__main__":
    import pytest_bazel

    pytest_bazel.main()

"""Lossless record primitives for native harness captures.

The raw byte record is authoritative. Parsed JSON is deliberately an always-present
wrapper so JSON ``null`` remains distinct from a missing database value.
"""

from __future__ import annotations

import base64
import hashlib
import json
from contextlib import suppress
from dataclasses import dataclass
from typing import Any


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def decode_b64(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


def json_wrapper(data: bytes) -> dict[str, Any]:
    """Return a non-null parsing diagnostic without modifying *data*."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        return {"state": "not_json", "error": {"kind": "decode_error", "offset": error.start}}
    try:
        return {"state": "parsed", "value": json.loads(text)}
    except json.JSONDecodeError as error:
        return {"state": "not_json", "error": {"kind": "json_error", "line": error.lineno, "column": error.colno}}


@dataclass(frozen=True, slots=True)
class RawRecord:
    """The shared immutable representation of a captured byte unit."""

    data: bytes
    run_sequence: int
    stream_sequence: int
    direction: str
    process_generation: int
    delimiter: bytes = b""
    eof_frame: bool = False

    def as_dict(self, *, wall_time: str, monotonic_ns: int) -> dict[str, Any]:
        full = self.data + self.delimiter
        payload: dict[str, Any] = {
            "run_sequence": self.run_sequence,
            "stream_sequence": self.stream_sequence,
            "direction": self.direction,
            "process_generation": self.process_generation,
            "wall_time": wall_time,
            "monotonic_ns": monotonic_ns,
            "raw_base64": b64(self.data),
            "byte_length": len(self.data),
            "sha256": sha256(self.data),
            "delimiter_base64": b64(self.delimiter),
            "wire_byte_length": len(full),
            "wire_sha256": sha256(full),
            "eof_frame": self.eof_frame,
            "parsed": json_wrapper(self.data),
        }
        with suppress(UnicodeDecodeError):
            payload["utf8"] = self.data.decode("utf-8")
        return payload

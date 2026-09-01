"""Arbitrary-chunk framing that preserves line delimiters and EOF tails."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class NewlineFramer:
    _pending: bytes = field(default=b"", init=False)

    def feed(self, chunk: bytes) -> list[tuple[bytes, bytes, bool]]:
        self._pending += chunk
        records: list[tuple[bytes, bytes, bool]] = []
        while True:
            newline = self._pending.find(b"\n")
            if newline < 0:
                return records
            end = newline + 1
            data = self._pending[:newline]
            delimiter = b"\n"
            if data.endswith(b"\r"):
                data, delimiter = data[:-1], b"\r\n"
            records.append((data, delimiter, False))
            self._pending = self._pending[end:]

    def finish(self) -> list[tuple[bytes, bytes, bool]]:
        if not self._pending:
            return []
        data, self._pending = self._pending, b""
        return [(data, b"", True)]

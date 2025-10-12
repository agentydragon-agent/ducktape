import json
import sys
from typing import IO, Any


def send_line_json(out: IO[bytes] | None, payload: dict[str, Any]) -> None:
    assert out is not None
    line = json.dumps(payload).encode() + b"\n"
    out.write(line)
    out.flush()


def read_line_json(inp: IO[bytes] | None, timeout: float | None = None) -> dict[str, Any] | None:
    assert inp is not None
    # Naive blocking read; tests wrap with timeouts on the process
    if not (line := inp.readline()):
        return None
    try:
        return json.loads(line.decode())
    except Exception:
        sys.stderr.write(f"[read_line_json] failed to parse: {line!r}\n")
        return None

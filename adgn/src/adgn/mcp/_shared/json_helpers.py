"""Common JSON parsing helpers with type safety."""

import asyncio
import json
import logging
import sys
from typing import IO, Any

logger = logging.getLogger(__name__)


async def read_line_json_dict_async(
    reader: asyncio.StreamReader, read_timeout: float | None = None
) -> dict[str, Any] | None:
    """Async read a line of JSON from a stream and return as dict or None.

    Ensures type safety by validating the parsed result is a dict.
    """
    try:
        # Read with timeout if specified
        if read_timeout:
            line_bytes = await asyncio.wait_for(reader.readline(), timeout=read_timeout)
        else:
            line_bytes = await reader.readline()

        if not line_bytes:
            return None

        result = json.loads(line_bytes.decode())
        if not isinstance(result, dict):
            sys.stderr.write(f"[read_line_json_dict] expected dict but got {type(result).__name__}: {line_bytes!r}\n")
            return None
        return result
    except TimeoutError:
        return None
    except Exception as e:
        sys.stderr.write(f"[read_line_json_dict] failed to parse: {e}\n")
        return None


def read_line_json_dict(inp: IO[bytes], timeout: float | None = None) -> dict[str, Any] | None:
    """Sync read a line of JSON from a stream and return as dict or None.

    Simplified sync version for test/subprocess contexts.
    Note: timeout is ignored in sync version.
    """
    line = inp.readline()
    if not line:
        return None

    try:
        result = json.loads(line.decode())
        if not isinstance(result, dict):
            logger.warning("JSON parse result was not a dict: %s", type(result).__name__)
            return None
        return result
    except Exception as e:
        # JSON parsing failure - log and return None per function contract
        logger.warning("Failed to parse JSON line: %s", e, exc_info=True)
        return None


async def send_line_json_async(writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
    """Async send a JSON payload as a line to a stream."""
    line = json.dumps(payload).encode() + b"\n"
    writer.write(line)
    await writer.drain()


def send_line_json(out: IO[bytes], payload: dict[str, Any]) -> None:
    """Sync send a JSON payload as a line to a stream."""
    line = json.dumps(payload).encode() + b"\n"
    out.write(line)
    out.flush()

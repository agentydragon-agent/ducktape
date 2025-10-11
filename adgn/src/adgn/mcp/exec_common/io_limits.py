from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Annotated

from pydantic import Field

# Cap for stdout/stderr/stdin bytes in exec-like servers

MAX_BYTES_CAP = 100_000

# Cap for execution timeout across exec-like servers (milliseconds)
# Keep reasonably low to avoid runaway processes; tune per product needs.
MAX_EXEC_TIMEOUT_MS = 300_000

# Pydantic-validated timeout type (milliseconds)
TimeoutMs = Annotated[int, Field(gt=0, le=MAX_EXEC_TIMEOUT_MS)]


class MaxBytesValidationError(ValueError):
    pass


def validate_max_bytes(n: int) -> int:
    """Validate max_bytes per spec: integer >= 0 and <= MAX_BYTES_CAP.

    Returns the value if valid, else raises MaxBytesValidationError.
    """
    if n < 0:
        raise MaxBytesValidationError("max_bytes must be >= 0")
    if n > MAX_BYTES_CAP:
        raise MaxBytesValidationError(f"max_bytes must be <= {MAX_BYTES_CAP}")
    return n


# Note: prefer using the above Annotated types directly in Pydantic models


@dataclass(slots=True)
class StreamReadResult:
    stored_text: str  # UTF-8 decoded with replacement; may be empty
    truncated: bool  # True if output exceeded the store_limit
    total_bytes: int  # total bytes produced by the stream (counted)


def clamp_stdin_bytes(stdin_text: str | None, limit: int) -> bytes:
    """Encode stdin_text to UTF-8 and clamp to at most limit bytes.

    Returns bytes to write to the child's stdin (no markers added).
    """
    if not stdin_text:
        return b""
    data = stdin_text.encode("utf-8", errors="replace")
    if limit <= 0:
        return b""
    if len(data) <= limit:
        return data
    return data[:limit]


def _decode_prefix(prefix: bytes) -> str:
    """Decode a byte prefix to UTF-8, replacing errors; avoid surrogate noise."""
    return prefix.decode("utf-8", errors="replace")


def read_stream_limited_sync(fh, store_limit: int, chunk_size: int = 8192) -> StreamReadResult:
    """Read a blocking binary stream to EOF, storing at most store_limit bytes.

    - Always drains to EOF to compute total_bytes
    - Returns stored_text (UTF-8), truncated flag, and total_bytes
    """
    assert store_limit >= 0
    stored = bytearray()
    total = 0
    while True:
        buf = fh.read(chunk_size)
        if not buf:
            break
        total += len(buf)
        # Store only up to the cap
        if len(stored) < store_limit:
            # How many bytes from this chunk can we still store?
            remaining = store_limit - len(stored)
            if remaining > 0:
                stored.extend(buf[:remaining])
        # else: we still need to drain to count total
    truncated = total > store_limit
    return StreamReadResult(
        stored_text=_decode_prefix(bytes(stored)),
        truncated=truncated,
        total_bytes=total,
    )


async def read_stream_limited_async(
    reader: asyncio.StreamReader, store_limit: int, chunk_size: int = 8192
) -> StreamReadResult:
    """Read an asyncio StreamReader to EOF, storing at most store_limit bytes.

    - Always drains to EOF to compute total_bytes
    - Returns stored_text (UTF-8), truncated flag, and total_bytes
    """
    assert store_limit >= 0
    stored = bytearray()
    total = 0
    while True:
        buf = await reader.read(chunk_size)
        if not buf:
            break
        total += len(buf)
        if len(stored) < store_limit:
            remaining = store_limit - len(stored)
            if remaining > 0:
                stored.extend(buf[:remaining])
    truncated = total > store_limit
    return StreamReadResult(
        stored_text=_decode_prefix(bytes(stored)),
        truncated=truncated,
        total_bytes=total,
    )

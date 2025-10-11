from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StreamOut(BaseModel):
    """Structured stream when truncated: include truncated_text and total size.

    When a stream fits entirely under the limit, servers return a plain string instead.
    """

    truncated_text: str
    total_bytes: int

    model_config = ConfigDict(extra="forbid")

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StreamOut(BaseModel):
    """Structured stream when truncated: include metadata and stored text.

    When a stream fits entirely under the limit, servers return a plain string instead.
    """

    text: str
    truncated: bool = True
    total_bytes: int

    model_config = ConfigDict(extra="forbid")

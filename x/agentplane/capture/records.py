"""Pydantic shapes for persisted capture evidence, not native provider frames."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TextRecord(BaseModel):
    time_ns: int = Field(ge=0)
    text: str


class RequestRecord(BaseModel):
    kind: Literal["request"]
    capture_request_id: str
    method: Literal["POST"]
    path_query: str
    body: str


class ResponseChunkRecord(BaseModel):
    kind: Literal["response_chunk"]
    capture_request_id: str
    ordinal: int = Field(ge=1)
    body: str


class ConnectionDroppedRecord(BaseModel):
    """One intentional upstream stream loss after visible assistant content."""

    kind: Literal["connection_dropped"]
    capture_request_id: str


class ProxyErrorRecord(BaseModel):
    kind: Literal["proxy_error"]
    capture_request_id: str
    error_kind: str


class CaptureMetadata(BaseModel):
    provider: Literal["claude", "codex"]
    scenario: str
    model: str

"""Common protocol messages used across all channels."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ChannelEnvelope(BaseModel):
    """Generic envelope for all channel messages."""

    channel: str
    event_id: int
    event_at: datetime
    payload: BaseModel
    model_config = ConfigDict(extra="forbid")


class Accepted(BaseModel):
    """Connection accepted acknowledgment."""

    type: Literal["accepted"] = "accepted"
    model_config = ConfigDict(extra="forbid")


class ErrorCode(StrEnum):
    INVALID_JSON = "INVALID_JSON"
    MISSING_FIELD = "MISSING_FIELD"
    INVALID_COMMAND = "INVALID_COMMAND"
    NO_AGENT = "NO_AGENT"
    AGENT_ERROR = "AGENT_ERROR"
    COMPONENT_UNAVAILABLE = "COMPONENT_UNAVAILABLE"


class ErrorEvt(BaseModel):
    """Error event."""

    type: Literal["error"] = "error"
    code: ErrorCode
    message: str | None = None
    details: dict | None = None
    model_config = ConfigDict(extra="forbid")


class HeartbeatEvt(BaseModel):
    """Heartbeat keepalive."""

    type: Literal["heartbeat"] = "heartbeat"
    interval_ms: int
    model_config = ConfigDict(extra="forbid")

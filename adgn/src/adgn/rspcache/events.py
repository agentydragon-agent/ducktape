from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from pydantic.type_adapter import TypeAdapter


class EventBase(BaseModel):
    """Base class for rspcache events emitted over PG NOTIFY."""

    type: str


class ResponseStatusEvent(EventBase):
    type: Literal["response_status"]
    key: str
    response_id: str | None = None
    status: str
    status_reason: str | None = None


class FrameAppendedEvent(EventBase):
    type: Literal["frame"]
    key: str
    response_id: str | None = None
    ordinal: int
    frame_type: str | None = None
    event_id: str | None = None


class APIKeyCreatedEvent(EventBase):
    type: Literal["api_key_created"]
    id: str
    name: str
    upstream_alias: str


class APIKeyRevokedEvent(EventBase):
    type: Literal["api_key_revoked"]
    id: str


EventPayload = ResponseStatusEvent | FrameAppendedEvent | APIKeyCreatedEvent | APIKeyRevokedEvent

_EVENT_ADAPTER = TypeAdapter(EventPayload)


def serialize_event(event: EventPayload) -> str:
    """Serialize an event payload to JSON for transport."""

    return event.model_dump_json()


def parse_event(data: str) -> EventPayload:
    """Parse a JSON payload into an event model."""

    return _EVENT_ADAPTER.validate_json(data)

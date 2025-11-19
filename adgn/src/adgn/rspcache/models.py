from __future__ import annotations

from enum import StrEnum
from typing import Any

from openai.types.responses import (
    Response as OpenAIResponse,
    ResponseCompletedEvent,
    ResponseCreatedEvent,
    ResponseError,
    ResponseFailedEvent,
    ResponseIncompleteEvent,
    ResponseInProgressEvent,
    ResponseQueuedEvent,
    ResponseStreamEvent,
    ResponseUsage,
)
from pydantic import BaseModel, ConfigDict, TypeAdapter, field_serializer

RESPONSE_ADAPTER: TypeAdapter[OpenAIResponse] = TypeAdapter(OpenAIResponse)
ERROR_ADAPTER: TypeAdapter[ResponseError] = TypeAdapter(ResponseError)
USAGE_ADAPTER: TypeAdapter[ResponseUsage] = TypeAdapter(ResponseUsage)


class ResponseStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    ERROR = "error"


class ErrorPayload(BaseModel):
    """Lightweight proxy error payload captured by the rspcache proxy."""

    message: str | None = None
    code: str | None = None
    detail: Any | None = None

    model_config = ConfigDict(extra="allow")


class FinalResponseSnapshot(BaseModel):
    """Canonical representation of a completed or errored response."""

    status: ResponseStatus
    response: OpenAIResponse | None = None
    error: ErrorPayload | None = None
    token_usage: ResponseUsage | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_serializer("status")
    def serialize_status(self, value: ResponseStatus) -> str:
        return value.value


def stream_event_response_id(event: ResponseStreamEvent) -> str | None:
    if isinstance(
        event,
        ResponseCreatedEvent
        | ResponseCompletedEvent
        | ResponseFailedEvent
        | ResponseInProgressEvent
        | ResponseIncompleteEvent
        | ResponseQueuedEvent,
    ):
        return event.response.id
    return None


def stream_event_usage(event: ResponseStreamEvent) -> ResponseUsage | None:
    if isinstance(
        event,
        ResponseCreatedEvent
        | ResponseCompletedEvent
        | ResponseFailedEvent
        | ResponseInProgressEvent
        | ResponseIncompleteEvent
        | ResponseQueuedEvent,
    ):
        return event.response.usage
    return None


def stream_event_final_response(event: ResponseStreamEvent) -> OpenAIResponse | None:
    if isinstance(
        event,
        ResponseCreatedEvent
        | ResponseCompletedEvent
        | ResponseFailedEvent
        | ResponseInProgressEvent
        | ResponseIncompleteEvent
        | ResponseQueuedEvent,
    ):
        return event.response
    return None

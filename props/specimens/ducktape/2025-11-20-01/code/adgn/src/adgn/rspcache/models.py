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


def response_from_event(event: ResponseStreamEvent) -> OpenAIResponse | None:
    """Return Response object for stream events that carry response payloads."""

    if isinstance(
        event,
        ResponseCreatedEvent
        | ResponseCompletedEvent
        | ResponseFailedEvent
        | ResponseInProgressEvent
        | ResponseIncompleteEvent
        | ResponseQueuedEvent,
    ):
        return RESPONSE_ADAPTER.validate_python(event.response)
    return None


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

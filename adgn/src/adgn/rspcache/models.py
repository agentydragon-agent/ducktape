from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from openai.types.responses import Response as OpenAIResponse, ResponseError, ResponseStreamEvent, ResponseUsage
from pydantic import BaseModel, ConfigDict, TypeAdapter, field_serializer

FRAME_ADAPTER: TypeAdapter[ResponseStreamEvent] = TypeAdapter(ResponseStreamEvent)
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


def stream_event_event_id(event: ResponseStreamEvent) -> str | None:
    event_id = getattr(event, "event_id", None)
    return event_id if isinstance(event_id, str) else None


def stream_event_response_id(event: ResponseStreamEvent) -> str | None:
    # Try response_id first
    response_id = getattr(event, "response_id", None)
    if isinstance(response_id, str):
        return response_id

    # Try response.id
    response = getattr(event, "response", None)
    if isinstance(response, Mapping):
        value = response.get("id")
        if isinstance(value, str):
            return value
    elif hasattr(response, "id"):
        value = getattr(response, "id", None)
        if isinstance(value, str):
            return value

    return None


def stream_event_usage(event: ResponseStreamEvent) -> ResponseUsage | None:
    # Try event.usage first
    usage_candidate = getattr(event, "usage", None)
    if isinstance(usage_candidate, ResponseUsage):
        return usage_candidate
    if isinstance(usage_candidate, Mapping):
        return parse_usage(usage_candidate)

    # Try event.response.usage
    response = getattr(event, "response", None)
    if isinstance(response, Mapping):
        usage_value = response.get("usage")
        if isinstance(usage_value, ResponseUsage):
            return usage_value
        if isinstance(usage_value, Mapping):
            return parse_usage(usage_value)
    elif hasattr(response, "usage"):
        usage_value = getattr(response, "usage", None)
        if isinstance(usage_value, ResponseUsage):
            return usage_value
        if isinstance(usage_value, Mapping):
            return parse_usage(usage_value)

    return None


def stream_event_final_response(event: ResponseStreamEvent) -> OpenAIResponse | None:
    response = getattr(event, "response", None)
    if response is not None:
        return parse_response(response)
    return None


def parse_response(value: OpenAIResponse | Mapping[str, object]) -> OpenAIResponse:
    if value is None:
        raise ValueError("response payload cannot be None")
    if isinstance(value, OpenAIResponse):
        return value
    return RESPONSE_ADAPTER.validate_python(value)


def parse_usage(value: ResponseUsage | Mapping[str, object]) -> ResponseUsage:
    if isinstance(value, ResponseUsage):
        return value
    return USAGE_ADAPTER.validate_python(value)

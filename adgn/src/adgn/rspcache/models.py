from __future__ import annotations

from enum import StrEnum
from typing import Any

from openai.types.responses import (
    Response as OpenAIResponse,
    ResponseError,
    ResponseStreamEvent,
    ResponseUsage,
)
from pydantic import BaseModel, ConfigDict, TypeAdapter

FRAME_ADAPTER = TypeAdapter(ResponseStreamEvent)
RESPONSE_ADAPTER = TypeAdapter(OpenAIResponse)
ERROR_ADAPTER = TypeAdapter(ResponseError)
USAGE_ADAPTER = TypeAdapter(ResponseUsage)


class ResponseStatus(StrEnum):
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

    @classmethod
    def from_db(
        cls,
        *,
        status: str,
        response_json: Any,
        error_json: Any,
        token_usage_json: Any,
    ) -> "FinalResponseSnapshot":
        return cls(
            status=ResponseStatus(status),
            response=parse_response(response_json) if response_json is not None else None,
            error=parse_error(error_json) if error_json is not None else None,
            token_usage=parse_usage(token_usage_json) if token_usage_json is not None else None,
        )

    def to_db_payload(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "response_json": dump_response(self.response),
            "error_json": dump_error(self.error),
            "token_usage_json": dump_usage(self.token_usage),
        }


def parse_stream_event(data: Any) -> ResponseStreamEvent:
    return FRAME_ADAPTER.validate_python(data)


def dump_stream_event(event: ResponseStreamEvent) -> dict[str, Any]:
    return event.model_dump(mode="json")


def stream_event_type(event: ResponseStreamEvent) -> str:
    return getattr(event, "type")


def stream_event_event_id(event: ResponseStreamEvent) -> str | None:
    payload = dump_stream_event(event)
    return payload.get("event_id")


def stream_event_response_id(event: ResponseStreamEvent) -> str | None:
    payload = dump_stream_event(event)
    response_id = payload.get("response_id")
    if response_id:
        return response_id
    response = payload.get("response")
    if isinstance(response, dict):
        return response.get("id")
    return None


def stream_event_usage(event: ResponseStreamEvent) -> ResponseUsage | None:
    payload = dump_stream_event(event)
    usage = payload.get("usage")
    if usage is not None:
        return parse_usage(usage)
    response = payload.get("response")
    if isinstance(response, dict):
        usage = response.get("usage")
        if usage is not None:
            return parse_usage(usage)
    return None


def stream_event_final_response(event: ResponseStreamEvent) -> OpenAIResponse | None:
    payload = dump_stream_event(event)
    response = payload.get("response")
    if response is not None:
        return parse_response(response)
    return None


def parse_response(value: Any) -> OpenAIResponse:
    if value is None:
        raise ValueError("response payload cannot be None")
    if isinstance(value, OpenAIResponse):
        return value
    return RESPONSE_ADAPTER.validate_python(value)


def dump_response(value: OpenAIResponse | None) -> Any:
    if value is None:
        return None
    return value.model_dump(mode="json")


def parse_error(value: Any) -> ErrorPayload:
    if value is None:
        return ErrorPayload()
    if isinstance(value, ErrorPayload):
        return value
    if isinstance(value, ResponseError):
        return ErrorPayload.model_validate(value.model_dump(mode="json"))
    if not isinstance(value, dict):
        raise ValueError("error payload must be a mapping")
    return ErrorPayload.model_validate(value)


def dump_error(value: ErrorPayload | None) -> Any:
    if value is None:
        return None
    return value.model_dump(mode="json")


def parse_usage(value: Any) -> ResponseUsage:
    if isinstance(value, ResponseUsage):
        return value
    return USAGE_ADAPTER.validate_python(value)


def dump_usage(value: ResponseUsage | None) -> Any:
    if value is None:
        return None
    return value.model_dump(mode="json")

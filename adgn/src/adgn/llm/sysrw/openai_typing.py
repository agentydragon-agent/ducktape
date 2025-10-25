from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Iterable, Iterator, Sequence, Union, get_args, get_origin

from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallParam,
    ChatCompletionToolParam,
)
from openai.types.responses import Response
from pydantic import TypeAdapter

try:  # OpenAI responses <= 0.8 (ResponseMessage family available)
    from openai.types.responses import (  # type: ignore[attr-defined]
        ResponseMessage as _ResponseMessage,
        ResponseMessageContentPart as _ResponseMessageContentPart,
    )

    ResponseMessageType = _ResponseMessage
    ResponseMessagePartType = _ResponseMessageContentPart
except ImportError:  # OpenAI responses >= 0.9 (ResponseOutputMessage etc.)
    from openai.types.responses import (  # type: ignore[attr-defined]
        ResponseOutputMessage,
        ResponseOutputRefusal,
        ResponseOutputText,
    )

    ResponseMessageType = ResponseOutputMessage
    ResponseMessagePartType = Union[ResponseOutputText, ResponseOutputRefusal]

try:
    from openai.types.responses import ResponseOutput  # type: ignore[attr-defined]
except ImportError:
    ResponseOutput = None  # type: ignore[assignment]

try:
    from openai.types.responses import (
        ResponseOutputToolCall as _ResponseOutputToolCall,  # type: ignore[attr-defined]
    )
except ImportError:
    _ResponseOutputToolCall = None  # type: ignore[assignment]

try:
    from openai.types.responses import ResponseFunctionToolCall  # type: ignore[attr-defined]
except ImportError:
    ResponseFunctionToolCall = None  # type: ignore[assignment]

_CHAT_MESSAGES = TypeAdapter(list[ChatCompletionMessageParam])
_CHAT_TOOL_CALLS = TypeAdapter(list[ChatCompletionMessageToolCallParam])
_CHAT_TOOL_PARAMS = TypeAdapter(list[ChatCompletionToolParam])
_RESPONSE_MESSAGES = TypeAdapter(list[ResponseMessageType])
_RESPONSE_PARTS = TypeAdapter(list[ResponseMessagePartType])


def _is_instance(value: Any, typ: Any) -> bool:
    origin = get_origin(typ)
    if origin is Union:
        return any(isinstance(value, arg) for arg in get_args(typ))
    return isinstance(value, typ)


def _is_iterable_of(items: Any, typ: Any) -> bool:
    return isinstance(items, list) and all(_is_instance(elem, typ) for elem in items)


def parse_chat_messages(obj: Any) -> list[ChatCompletionMessageParam]:
    if obj is None:
        return []
    if isinstance(obj, ChatCompletionMessageParam):
        return [obj]
    if _is_iterable_of(obj, ChatCompletionMessageParam):
        return list(obj)
    return _CHAT_MESSAGES.validate_python(obj)


def parse_tool_params(obj: Any) -> list[ChatCompletionToolParam]:
    if obj is None:
        return []
    if isinstance(obj, ChatCompletionToolParam):
        return [obj]
    if _is_iterable_of(obj, ChatCompletionToolParam):
        return list(obj)
    return _CHAT_TOOL_PARAMS.validate_python(obj)


def parse_response_messages(obj: Any) -> list[ResponseMessageType]:
    if obj is None:
        return []
    if _is_instance(obj, ResponseMessageType):
        return [obj]
    if _is_iterable_of(obj, ResponseMessageType):
        return list(obj)
    return _RESPONSE_MESSAGES.validate_python(obj)


def parse_response_parts(obj: Any) -> list[ResponseMessagePartType]:
    if obj is None:
        return []
    if _is_instance(obj, ResponseMessagePartType):
        return [obj]
    if _is_iterable_of(obj, ResponseMessagePartType):
        return list(obj)
    return _RESPONSE_PARTS.validate_python(obj)


def parse_response(obj: Any) -> Response:
    if isinstance(obj, Response):
        return obj
    return Response.model_validate(obj)


def dump_chat_messages(messages: Sequence[ChatCompletionMessageParam]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        if hasattr(msg, "model_dump"):
            out.append(msg.model_dump(mode="json", exclude_none=True))  # type: ignore[no-untyped-call]
        else:
            out.append(dict(msg))
    return out


def dump_response_messages(messages: Sequence[ResponseMessageType]) -> list[dict[str, Any]]:
    dumped: list[dict[str, Any]] = []
    for msg in messages:
        if hasattr(msg, "model_dump"):
            dumped.append(msg.model_dump(mode="json", exclude_none=True))
        else:
            dumped.append(dict(msg))
    return dumped


def message_role(message: ResponseMessageType | ChatCompletionMessageParam) -> str:
    base = getattr(message, "role", None) or getattr(message, "message_role", None)
    return (base or "").lower()


def message_content(message: ResponseMessageType | ChatCompletionMessageParam) -> Any:
    return getattr(message, "content", None)


def message_content_as_text(message: ResponseMessageType | ChatCompletionMessageParam) -> str:
    content = message_content(message)
    if isinstance(content, str):
        return content
    parts = parse_response_parts(content)
    if parts:
        return "\n".join(iter_resolved_text(parts))
    return ""


def iter_resolved_text(parts: Iterable[ResponseMessagePartType]) -> Iterator[str]:
    for part in parts:
        text = None
        for attr in ("text", "input_text", "content", "refusal"):
            value = getattr(part, attr, None)
            if value:
                text = value
                break
        if text is None and isinstance(part, dict):
            text = (
                part.get("text")
                or part.get("input_text")
                or part.get("content")
                or part.get("refusal")
            )
        if isinstance(text, str) and text:
            yield text
            continue
        if isinstance(text, list):
            fragments: list[str] = []
            for entry in text:
                if isinstance(entry, str):
                    fragments.append(entry)
                elif isinstance(entry, dict):
                    for key in ("text", "input_text", "content", "refusal"):
                        val = entry.get(key)
                        if isinstance(val, str):
                            fragments.append(val)
            if fragments:
                yield "\n".join(fragments)
            continue
        if text is not None:
            yield str(text)


def message_tool_calls(
    message: ResponseMessageType | ChatCompletionMessageParam,
) -> list[ChatCompletionMessageToolCallParam]:
    value = getattr(message, "tool_calls", None) or []
    if _is_iterable_of(value, ChatCompletionMessageToolCallParam):
        return list(value)
    return _CHAT_TOOL_CALLS.validate_python(value)


def tool_call_arguments(call: ChatCompletionMessageToolCallParam) -> str:
    func = getattr(call, "function", None)
    args = getattr(func, "arguments", None) if func is not None else None
    return args if isinstance(args, str) else ""


def iter_tool_calls_from_response(response: Response) -> Iterator[SimpleNamespace]:
    output = getattr(response, "output", None) or []
    for item in output:
        yield from _iter_tool_calls_from_item(item)


def _iter_tool_calls_from_item(item: Any) -> Iterator[SimpleNamespace]:
    item_type, item_data = _response_item_payload(item)
    if item_type in {"tool_call", "function_call", "custom_tool_call"}:
        payload = _tool_payload(item, item_data)
        tool_call = _make_tool_call(payload, item_data if item_data is not None else item)
        if tool_call is not None:
            yield tool_call
        return
    if item_type == "message" and item_data:
        for part in item_data.get("content", []) or []:
            if not isinstance(part, dict):
                continue
            tool_call_data = part.get("tool_call")
            if not tool_call_data:
                continue
            payload = tool_call_data.get("function") or tool_call_data
            tool_call = _make_tool_call(payload, tool_call_data)
            if tool_call is not None:
                yield tool_call


def _response_item_payload(item: Any) -> tuple[str | None, dict[str, Any] | None]:
    item_type = getattr(item, "type", None)
    item_data: dict[str, Any] | None = None
    if hasattr(item, "model_dump"):
        try:
            item_data = item.model_dump(mode="json", exclude_none=True)
            item_type = item_type or item_data.get("type")
        except TypeError:
            item_data = None
    elif isinstance(item, dict):
        item_data = item
        item_type = item_type or item_data.get("type")
    return item_type, item_data


def _tool_payload(item: Any, data: dict[str, Any] | None) -> Any:
    if hasattr(item, "function"):
        return item.function
    if data and isinstance(data.get("function"), dict):
        return data["function"]
    if data:
        return data
    if ResponseFunctionToolCall is not None and isinstance(item, ResponseFunctionToolCall):
        return item
    return item


def _make_tool_call(payload: Any, raw: Any) -> SimpleNamespace | None:
    if payload is None:
        return None
    name, arguments = _extract_name_and_arguments(payload)
    call_id = getattr(payload, "call_id", None)
    tool_id = getattr(payload, "id", None)
    status = getattr(payload, "status", None)
    type_name = getattr(payload, "type", None)
    if isinstance(payload, dict):
        call_id = payload.get("call_id", call_id)
        tool_id = payload.get("id", tool_id)
        status = payload.get("status", status)
        type_name = payload.get("type", type_name)
    function_ns = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(
        function=function_ns,
        call_id=call_id,
        id=tool_id,
        status=status,
        type=type_name,
        raw=raw,
    )


def _extract_name_and_arguments(payload: Any) -> tuple[str | None, Any]:
    if hasattr(payload, "function"):
        func = getattr(payload, "function")
        return getattr(func, "name", None), getattr(func, "arguments", None)
    name = getattr(payload, "name", None)
    arguments = getattr(payload, "arguments", None)
    if isinstance(payload, dict):
        function_section = payload.get("function")
        if isinstance(function_section, dict):
            name = function_section.get("name", name)
            arguments = function_section.get("arguments", arguments)
        else:
            name = payload.get("name", name)
            arguments = payload.get("arguments", arguments)
    return name, arguments

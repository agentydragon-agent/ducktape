from __future__ import annotations

from openai.types.responses import Response, ResponseOutputMessage, ResponseOutputText
from openai.types.responses.response_create_params import (
    ResponseCreateParamsNonStreaming as Req,
)
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_usage import (
    InputTokensDetails,
    OutputTokensDetails,
    ResponseUsage,
)

DEFAULT_MODEL = "gpt-4.1-mini"


def _usage_zeros() -> ResponseUsage:
    return ResponseUsage(
        input_tokens=0,
        input_tokens_details=InputTokensDetails(cached_tokens=0),
        output_tokens=0,
        output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
        total_tokens=0,
    )


def make_assistant_text_response(
    *,
    text: str,
    request: Req | None = None,
    model: str | None = None,
    id_: str = "resp_msg",
    msg_id: str = "msg1",
) -> Response:
    """Minimal assistant text Response using real SDK types, no getattr.

    - status: completed
    - output: one assistant message with one text block
    - copies from request if present: model, tool_choice, parallel_tool_calls
    - usage: zeros (tests rarely care about this)
    """
    # Model
    model_final = (
        model
        if model is not None
        else (request.model if request is not None else DEFAULT_MODEL)
    )
    # Tool choice (only pass through simple string; keep minimal)
    tool_choice = (
        request.tool_choice
        if (request is not None and isinstance(request.tool_choice, str))
        else "auto"
    )
    # Parallel flag
    parallel = (
        request.parallel_tool_calls
        if (request is not None and request.parallel_tool_calls is not None)
        else False
    )

    msg = ResponseOutputMessage(
        id=msg_id,
        type="message",
        role="assistant",
        status="completed",
        content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
    )
    return Response(
        id=id_,
        created_at=1,
        model=model_final,
        object="response",
        output=[msg],
        parallel_tool_calls=parallel,
        tool_choice=tool_choice,
        tools=[],
        usage=_usage_zeros(),
    )


def make_function_call_response(
    *,
    tool_name: str,
    arguments_json: str,
    request: Req | None = None,
    id_: str = "resp_fc",
    call_id: str = "call_1",
) -> Response:
    """Response containing a single function tool call output item."""
    model_final = (
        request.model
        if (request is not None and request.model is not None)
        else DEFAULT_MODEL
    )
    fc = ResponseFunctionToolCall(
        type="function_call", name=tool_name, call_id=call_id, arguments=arguments_json
    )
    tool_choice = (
        request.tool_choice
        if (request is not None and isinstance(request.tool_choice, str))
        else "auto"
    )
    parallel = (
        request.parallel_tool_calls
        if (request is not None and request.parallel_tool_calls is not None)
        else False
    )
    return Response(
        id=id_,
        created_at=1,
        model=model_final,
        object="response",
        output=[fc],
        parallel_tool_calls=parallel,
        tool_choice=tool_choice,
        tools=[],
        usage=_usage_zeros(),
    )

from __future__ import annotations

from typing import Any
import json

from adgn.llm.openai_utils.model import (
    ResponsesResult as Response,
    ResponsesRequest as Req,
    AssistantResponseMessage,
    FunctionCallOut,
    Usage as ResponseUsage,
    UserMessage as ResponseInputMessageItem,
    InputTextPart as ResponseInputTextParam,
    FunctionCallItem as ResponseFunctionToolCall,
)

DEFAULT_MODEL = "gpt-4.1-mini"


def _usage_zeros() -> ResponseUsage:
    return ResponseUsage(input_tokens=0, output_tokens=0, total_tokens=0)


def make_assistant_text_response(
    *,
    text: str,
    request: Req | None = None,
    model: str | None = None,
    id_: str = "resp_msg",
    msg_id: str = "msg1",
) -> Response:
    """Minimal assistant text Response using adapter types."""
    return Response(
        id=id_, usage=_usage_zeros(), output=[AssistantResponseMessage(text=text)]
    )


def make_function_call_response(
    *,
    tool_name: str,
    arguments_json: str,
    request: Req | None = None,
    id_: str = "resp_fc",
    call_id: str = "call_1",
) -> Response:
    """Response containing a single function tool call output item (adapter types)."""
    return Response(
        id=id_,
        usage=_usage_zeros(),
        output=[
            FunctionCallOut(name=tool_name, call_id=call_id, arguments=arguments_json)
        ],
    )


# ---- Input item builders (for agent inserts) ----


def make_input_user_text(text: str, id_: str | None = None) -> ResponseInputMessageItem:
    """Typed user input_text message for our adapter request model."""
    content = [ResponseInputTextParam(text=text)]
    return ResponseInputMessageItem(role="user", content=content)


def make_input_function_call(
    *, name: str, call_id: str, arguments: dict[str, Any] | str
) -> ResponseFunctionToolCall:
    """Typed function_call input item (adapter model)."""
    args_str = json.dumps(arguments) if isinstance(arguments, dict) else str(arguments)
    return ResponseFunctionToolCall(name=name, call_id=call_id, arguments=args_str)


def make_input_function_call_output(*, call_id: str, output: str) -> dict[str, Any]:
    """function_call_output input item for adapter requests."""
    return {"type": "function_call_output", "call_id": call_id, "output": output}

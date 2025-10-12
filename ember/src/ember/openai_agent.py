from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar, Union

from openai import AsyncOpenAI
from openai.types.responses import (
    FunctionToolParam,
    Response,
    ResponseFunctionToolCall,
    ResponseInputItemParam,
)
from openai.types.responses.easy_input_message import EasyInputMessage
from openai.types.responses.response_input_item import (
    FunctionCallOutput as ResponseFunctionCallOutput,
)
from openai.types.responses.response_input_text import ResponseInputText
from openai.types.shared.reasoning_effort import ReasoningEffort
from openai.types.shared_params.reasoning import Reasoning
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from .config import OpenAISettings
from .history import ConversationHistory

logger = logging.getLogger(__name__)

ToolPayload = Union[BaseModel, str]
ToolHandler = Callable[[BaseModel], Awaitable[ToolPayload]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    handler: ToolHandler
    strict: bool = False

    @property
    def input_model(self) -> type[BaseModel]:
        return _first_handler_arg(self.handler)

    def to_param(self) -> FunctionToolParam:
        return FunctionToolParam(
            name=self.name,
            type="function",
            description=self.description,
            parameters=_json_schema_from_model(self.input_model),
            strict=self.strict,
        )


class RunShellCommandArgs(BaseModel):
    command: str
    model_config = ConfigDict(extra="forbid")


class YieldControlArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShellCommandResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    model_config = ConfigDict(extra="forbid")


class YieldControlResult(BaseModel):
    status: str = "waiting_for_matrix"
    model_config = ConfigDict(extra="forbid")


class OpenAIAgent:
    def __init__(self, settings: OpenAISettings, history: ConversationHistory, client: AsyncOpenAI) -> None:
        self._settings = settings
        self._history = history
        self._client = client
        self._model = settings.model
        self._wait_for_matrix = False

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, value: str) -> None:
        if not value:
            raise ValueError("model must be a non-empty string")
        self._model = value

    @property
    def waiting_for_matrix(self) -> bool:
        return self._wait_for_matrix

    async def handle_user_message(self, content: str) -> None:
        self._wait_for_matrix = False
        user_message = EasyInputMessage(
            type="message",
            role="user",
            content=[ResponseInputText(type="input_text", text=content)],
        )
        self._history.append_input(_serialize_input_item(user_message))

        await self._model_loop()

    async def _model_loop(self) -> None:
        iteration = 0
        while True:
            iteration += 1
            input_payload = self._history.build_input_items(self._settings.system_prompt)
            logger.info("Sampling model (iteration %d)", iteration)
            response = await self._client.responses.create(
                model=self._model,
                input=input_payload,
                tools=self.tools,
                tool_choice="required",
                include=self._settings.include,
                reasoning=_build_reasoning_payload(self._settings.reasoning_effort),
            )
            self._history.append_response(response)

            tool_calls = [
                output for output in response.output if isinstance(output, ResponseFunctionToolCall)
            ]
            if not tool_calls:
                logger.warning(
                    "Model response contained no tool calls; stopping after %d iterations",
                    iteration,
                )
                break

            for tool_call in tool_calls:
                await self._execute_tool(tool_call)

            if self._wait_for_matrix:
                logger.info("Model yielded control after %d iterations", iteration)
                break

    async def _execute_tool(self, tool_call: ResponseFunctionToolCall) -> None:
        spec = self.tool_specs.get(tool_call.name)
        if spec is None:
            raise RuntimeError(f"Unknown tool {tool_call.name}")
        args = _parse_arguments(spec.input_model, tool_call.arguments)
        payload = await spec.handler(args)
        self._history.append_input(_function_call_output(tool_call.call_id, payload))

    async def _handle_run_shell_command(
        self, args: RunShellCommandArgs
    ) -> ToolPayload:
        return await _run_command(args.command)

    async def _handle_yield_control(
        self, args: YieldControlArgs
    ) -> ToolPayload:
        self._wait_for_matrix = True
        return YieldControlResult()

    @property
    def tool_specs(self) -> dict[str, ToolSpec]:
        return {
            spec.name: spec
            for spec in (
                ToolSpec(
                    name="run_shell_command",
                    description="Execute a shell command inside the container (e.g., matrix CLI).",
                    handler=self._handle_run_shell_command,
                ),
                ToolSpec(
                    name="yield_control",
                    description=(
                        "Call when there is nothing to do. The runtime will resume once new Matrix messages arrive."
                    ),
                    handler=self._handle_yield_control,
                ),
            )
        }

    @property
    def tools(self) -> list[FunctionToolParam]:
        return [spec.to_param() for spec in self.tool_specs.values()]

def _json_schema_from_model(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    parameters: dict[str, Any] = {
        "type": schema.get("type", "object"),
        "properties": schema.get("properties", {}),
    }
    required = schema.get("required")
    if required:
        parameters["required"] = required
    return parameters


def _build_reasoning_payload(effort: ReasoningEffort) -> Reasoning:
    payload: Reasoning = {"summary": "auto"}
    if effort:
        payload["effort"] = effort
    return payload


TArgs = TypeVar("TArgs", bound=BaseModel)


def _parse_arguments(model: type[TArgs], raw: str | None) -> TArgs:
    try:
        return model.model_validate_json(raw or "{}")
    except ValidationError as exc:
        raise RuntimeError(f"Invalid payload for {model.__name__}: {exc}") from exc


def _first_handler_arg(handler: ToolHandler) -> type[BaseModel]:
    from inspect import signature
    from typing import get_type_hints

    sig = signature(handler)
    params = list(sig.parameters.values())
    if not params:
        raise RuntimeError("Tool handler must accept at least one argument")

    hints = get_type_hints(handler)
    first_param = params[0]
    annotation = hints.get(first_param.name, first_param.annotation)
    if annotation is first_param.empty or not isinstance(annotation, type) or not issubclass(annotation, BaseModel):
        raise RuntimeError("Tool handler argument must be a Pydantic BaseModel subclass")
    return annotation


async def _run_command(command: str) -> ShellCommandResult:
    logger.info("Executing command: %s", command)
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
    except asyncio.TimeoutError as exc:  # pragma: no cover - safety guard
        proc.kill()
        stdout, stderr = await proc.communicate()
        stdout = stdout or b""
        stderr = stderr or b""
        return ShellCommandResult(
            exit_code=124,
            stdout=_decode_stream(stdout),
            stderr=_decode_stream(stderr),
            timed_out=True,
        )

    stdout_text = _decode_stream(stdout)
    stderr_text = _decode_stream(stderr)
    return ShellCommandResult(exit_code=proc.returncode or 0, stdout=stdout_text, stderr=stderr_text)


def _decode_stream(payload: bytes, limit: int = 4000) -> str:
    return payload.decode("utf-8", errors="replace")[:limit]


def _serialize_input_item(model: BaseModel) -> ResponseInputItemParam:
    return _INPUT_ITEM_ADAPTER.validate_python(
        model.model_dump(mode="python", exclude_none=True)
    )

def _function_call_output(call_id: str, payload: ToolPayload) -> ResponseInputItemParam:
    output = payload.model_dump_json() if isinstance(payload, BaseModel) else payload
    return _serialize_input_item(
        ResponseFunctionCallOutput(type="function_call_output", call_id=call_id, output=output)
    )


_INPUT_ITEM_ADAPTER: TypeAdapter[ResponseInputItemParam] = TypeAdapter(ResponseInputItemParam)

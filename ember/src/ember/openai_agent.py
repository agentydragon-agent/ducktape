from __future__ import annotations

import asyncio
import logging
from typing import TypeVar

from openai import AsyncOpenAI
from openai.types.responses import (
    FunctionToolParam,
    Response,
    ResponseFunctionToolCall,
    ResponseInputItemParam,
)
from openai.types.shared.reasoning_effort import ReasoningEffort
from openai.types.shared_params.reasoning import Reasoning
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from .config import OpenAISettings
from .history import ConversationHistory

logger = logging.getLogger(__name__)


class RunShellCommandArgs(BaseModel):
    command: str
    model_config = ConfigDict(extra="forbid")


class YieldControlArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShellCommandResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
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
        self._tools: list[FunctionToolParam] = _build_tools()

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
        user_item = _INPUT_ITEM_ADAPTER.validate_python(
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": content}],
            }
        )
        self._history.append_input(user_item)

        input_payload = self._history.build_input_items(self._settings.system_prompt)
        response = await self._client.responses.create(
            model=self._model,
            input=input_payload,
            tools=self._tools,
            tool_choice="required",
            include=self._settings.include,
            reasoning=_build_reasoning_payload(self._settings.reasoning_effort),
        )
        self._history.append_response(response)
        await self._process_response(response)

    async def _process_response(self, response: Response) -> None:
        if not (
            tool_calls := [
                output for output in response.output if isinstance(output, ResponseFunctionToolCall)
            ]
        ):
            raise RuntimeError("Model must return at least one tool call")

        for tool_call in tool_calls:
            await self._execute_tool(tool_call)

    async def _execute_tool(self, tool_call: ResponseFunctionToolCall) -> None:
        name = tool_call.name
        if name == "run_shell_command":
            args = _parse_arguments(RunShellCommandArgs, tool_call.arguments)
            result = await _run_command(args.command)
            function_output = _INPUT_ITEM_ADAPTER.validate_python(
                {
                    "type": "function_call_output",
                    "call_id": tool_call.call_id,
                    "output": result.model_dump_json(),
                }
            )
            self._history.append_input(function_output)
            return

        if name == "yield_control":
            _parse_arguments(YieldControlArgs, tool_call.arguments)
            self._wait_for_matrix = True
            yield_item = _INPUT_ITEM_ADAPTER.validate_python(
                {
                    "type": "function_call_output",
                    "call_id": tool_call.call_id,
                    "output": YieldControlResult().model_dump_json(),
                }
            )
            self._history.append_input(yield_item)
            return

        raise RuntimeError(f"Unknown tool {name}")


def _build_tools() -> list[FunctionToolParam]:
    return [
        FunctionToolParam(
            name="run_shell_command",
            type="function",
            description="Execute a shell command inside the container (e.g., matrix CLI).",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Command to run in the shell.",
                    }
                },
                "required": ["command"],
            },
            strict=False,
        ),
        FunctionToolParam(
            name="yield_control",
            type="function",
            description="Call when there is nothing to do. The runtime will resume once new Matrix messages arrive.",
            parameters={"type": "object", "properties": {}},
            strict=False,
        ),
    ]


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
        raise RuntimeError("Command timed out") from exc

    stdout_text = stdout.decode("utf-8", errors="replace")[:4000]
    stderr_text = stderr.decode("utf-8", errors="replace")[:4000]
    return ShellCommandResult(exit_code=proc.returncode or 0, stdout=stdout_text, stderr=stderr_text)


_INPUT_ITEM_ADAPTER: TypeAdapter[ResponseInputItemParam] = TypeAdapter(ResponseInputItemParam)

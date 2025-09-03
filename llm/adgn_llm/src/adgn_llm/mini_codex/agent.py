from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import openai
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)
from pydantic import BaseModel
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .local_server import LocalServer
from .mcp_manager import McpManager

# Unified tool source mapping
# Each value is either a LocalServer instance or a stdio dict with keys: command, args?, env?
ToolMap = dict[str, Any]
DEFAULT_MODEL = "o4-mini"
SYSTEM_INSTRUCTIONS = "You are a code agent. Be concise."

def _is_retryable(err: BaseException) -> bool:
    if isinstance(err, APITimeoutError | APIConnectionError | RateLimitError):
        return True
    if isinstance(err, APIStatusError):
        return isinstance(err.status_code, int) and err.status_code >= 500
    return False

@retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=0.5),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _responses_create_with_retry(client: openai.OpenAI, **params: Any):
    return client.responses.create(**params)

def _openai_client() -> openai.OpenAI:
    # Let the SDK discover configuration from environment; no manual key handling here
    return openai.OpenAI()


class ToolPolicy(StrEnum):
    AUTO = "auto"
    REQUIRED = "required"
    NONE = "none"


@dataclass
class ToolRun:
    name: str
    args: dict[str, Any]
    result: dict[str, Any]
    latency: timedelta
    error: str | None = None


@dataclass
class Metrics:
    turns: int = 0
    tool_calls: int = 0
    total_latency: timedelta = timedelta(0)


@dataclass
class AgentResult:
    text: str
    sequence: list[AgentEvent]   # linearized: assistant_text, tool_call, tool_output
    metrics: Metrics


AgentEvent = dict[str, Any]
AgentEventHandler = Callable[[AgentEvent], Any]


def load_mcp_file(path: str) -> ToolMap:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    servers = data.get("mcpServers") or {}
    if not isinstance(servers, dict):  # defensive
        raise ValueError(".mcp.json: mcpServers must be object")
    # Keep as stdio dicts; MiniCodex will split
    return {name: cfg for name, cfg in servers.items()}


class MiniCodex:
    def __init__(
        self,
        *,
        model: str,
        system: str | None,
        tool_policy: ToolPolicy | str,
        on_event: AgentEventHandler | None,
        mcp: McpManager,
        client: openai.OpenAI | None = None,
    ) -> None:
        self._model = model
        self._system = system or SYSTEM_INSTRUCTIONS
        self._tool_policy = ToolPolicy(tool_policy) if not isinstance(tool_policy, ToolPolicy) else tool_policy
        self._on_event = on_event
        self._mcp = mcp
        self._client = client or _openai_client()
        self._messages: list[Message] = []  # user/assistant only
        self._metrics = Metrics()

    @classmethod
    async def start(
        cls,
        *,
        model: str,
        tools: ToolMap,
        system: str | None = None,
        tool_policy: ToolPolicy | str = ToolPolicy.AUTO,
        on_event: AgentEventHandler | None = None,
        client: openai.OpenAI | None = None,
    ) -> MiniCodex:
        # Split ToolMap → stdio servers + local servers
        stdio_servers: dict[str, dict[str, Any]] = {}
        local_servers: list[LocalServer] = []
        for name, val in (tools or {}).items():
            if isinstance(val, LocalServer):
                local_servers.append(val)
            elif isinstance(val, dict) and "command" in val:
                stdio_servers[name] = {
                    "command": val["command"],
                    "args": val.get("args") or [],
                    "env": val.get("env") or {},
                }
            else:
                raise ValueError(f"Unsupported tool source for {name!r}")
        mcp = await McpManager.from_servers(stdio_servers, local=None, local_servers=local_servers)
        return cls(model=model, system=system, tool_policy=tool_policy, on_event=on_event, mcp=mcp, client=client)

    def tools(self) -> list[dict[str, Any]]:
        return self._mcp.list_tools()

    @property
    def messages(self) -> list[dict[str, Any]]:
        return dump_messages_for_api(self._messages)

    async def run(self, user_text: str, stream: bool = False) -> AgentResult | AsyncIterator[AgentEvent]:
        if stream:
            # Streaming events optional: for now, just yield a single final event using non-stream path
            async def _gen() -> AsyncIterator[AgentEvent]:
                res = await self.run(user_text, stream=False)  # type: ignore[assignment]
                yield {"kind": "final", "result": res}
            return _gen()

        # 1) append the user message
    
        self._messages.append(UserMessage(role="user", content=user_text))

        # 2) Execute turns until model stops requesting tools
        sequence: list[AgentEvent] = []
        assistant_text_chunks: list[str] = []
        prior_tool_calls: list[dict[str, Any]] | None = None
        pending_tool_outputs: list[FunctionCallOutput] | None = None

        while True:
            # Build instructions with server descriptions
            instructions = self._system
            extra = self._mcp.instruction_block()
            if extra:
                instructions = f"{instructions}\n\n{extra}"

            # Prepare input per Responses API threading rules
            if pending_tool_outputs:
                input_payload = dump_messages_for_api(self._messages)
                if prior_tool_calls:
                    input_payload += prior_tool_calls
                input_payload += [t.model_dump(exclude_none=True) for t in pending_tool_outputs]
            else:
                input_payload = dump_messages_for_api(self._messages)

            resp = _responses_create_with_retry(
                self._client,
                model=self._model,
                input=input_payload,
                instructions=instructions,
                stream=False,
                tool_choice=self._tool_policy.value,
                store=False,
                tools=self._mcp.list_tools(),
            )

            # Parse output
            prior_tool_calls = []
            requires: list[ResponseFunctionToolCall] = []
            turn_assistant_text = []
            for item in resp.output:
                if isinstance(item, ResponseOutputMessage):
                    for part in item.content:
                        if isinstance(part, ResponseOutputText) and part.text:
                            turn_assistant_text.append(part.text)
                elif isinstance(item, ResponseFunctionToolCall):
                    requires.append(item)
                    prior_tool_calls.append(item.model_dump(exclude_none=True))

            # Add assistant text to transcript/messages
            if turn_assistant_text:
                combined = "\n".join([t for t in turn_assistant_text if t])
                assistant_text_chunks.append(combined)
                msg = AssistantMessage(role="assistant", content=combined)
                self._messages.append(msg)
                evt = {"kind": "assistant_text", "text": combined}
                sequence.append(evt)
                if self._on_event:
                    await maybe_await(self._on_event, evt)

            # If model didn't call any tools, stop
            if not requires:
                break

            # Execute tools and prepare function_call_output list
            pending_tool_outputs = []
            for fc in requires:
                name = fc.name
                start = time.perf_counter()
                try:
                    args = json.loads(fc.arguments)
                except json.JSONDecodeError:
                    args = {}
                result = await self._mcp.call_tool(name, args if isinstance(args, dict) else {})
                latency = timedelta(seconds=(time.perf_counter() - start))
                call_evt = {"kind": "tool_call", "name": name, "args": args, "call_id": fc.call_id}
                out_evt = {"kind": "tool_output", "name": name, "result": result, "latency": latency, "error": result.get("stderr")}
                sequence.append(call_evt)
                sequence.append(out_evt)
                if self._on_event:
                    await maybe_await(self._on_event, call_evt)
                    await maybe_await(self._on_event, out_evt)
                pending_tool_outputs.append(
                    FunctionCallOutput(
                        type="function_call_output",
                        call_id=fc.call_id,
                        output=json.dumps(result),
                    ),
                )

            # Loop continues; send tool outputs + prior tool calls back next turn
            self._metrics.tool_calls += len(requires)

        # Finalize result
        self._metrics.turns += 1
        text = "\n".join(assistant_text_chunks)
        return AgentResult(text=text, sequence=sequence, metrics=self._metrics)

    async def close(self) -> None:
        await self._mcp.close()


# ==== Pydantic message models (local, to avoid cross-module deps) ====
class UserMessage(BaseModel):
    role: Literal["user"]
    content: str

class AssistantMessage(BaseModel):
    role: Literal["assistant"]
    content: str

class FunctionCallOutput(BaseModel):
    type: Literal["function_call_output"]
    call_id: str
    output: str

Message = UserMessage | AssistantMessage | FunctionCallOutput

def dump_messages_for_api(messages: list[Message]) -> list[dict[str, Any]]:
    return [m.model_dump(exclude_none=True) for m in messages]


async def maybe_await(fn: AgentEventHandler, event: AgentEvent) -> None:
    res = fn(event)
    if hasattr(res, "__await__"):
        await res  # type: ignore[misc]

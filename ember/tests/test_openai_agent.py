from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, cast

from openai import AsyncOpenAI
from openai.types.responses import (
    FunctionTool,
    Response,
    ResponseFunctionToolCall,
    ResponseReasoningItem,
    Tool,
)
from openai.types.responses.response_reasoning_item import Summary
import pytest

from ember.config import OpenAISettings
from ember.history import ConversationHistory
import ember.openai_agent as openai_agent
from ember.openai_agent import (
    OpenAIAgent,
    ShellCommandResult,
)


@pytest.fixture
def settings() -> OpenAISettings:
    return OpenAISettings(
        api_key="test-key",
        model="gpt-5",
        system_prompt="system prompt",
    )


@pytest.fixture
def history(tmp_path: Path) -> ConversationHistory:
    return ConversationHistory(tmp_path / "history.jsonl")


def _make_openai_client(api_key: str, response: Response) -> AsyncOpenAI:
    client = AsyncOpenAI(api_key=api_key)

    async def _create(**kwargs):  # type: ignore[no-untyped-def]
        return response

    setattr(client.responses, "create", _create)
    return client


@pytest.mark.asyncio
async def test_agent_runs_shell_command(monkeypatch: pytest.MonkeyPatch, settings: OpenAISettings, history: ConversationHistory) -> None:
    response = _response_with_tool_call(
        call_id="call-1",
        tool_name="run_shell_command",
        arguments='{"command": "echo hi"}',
    )
    client = _make_openai_client(settings.api_key, response)

    async def fake_run_command(command: str) -> ShellCommandResult:
        return ShellCommandResult(exit_code=0, stdout=f"ran {command}", stderr="")

    monkeypatch.setattr(openai_agent, "_run_command", fake_run_command)

    agent = OpenAIAgent(settings, history, client)
    await agent.handle_user_message("incoming message")

    assert not agent.waiting_for_matrix

    items = [cast(Mapping[str, object], item) for item in history.build_input_items(settings.system_prompt)]
    reasoning_items = [item for item in items if item.get("type") == "reasoning"]
    assert reasoning_items
    reasoning_model = ResponseReasoningItem.model_validate(reasoning_items[0])
    assert reasoning_model.encrypted_content == "ciphertext"
    assert reasoning_model.content in (None, [])
    outputs = [item for item in items if item.get("type") == "function_call_output"]
    assert outputs
    output_payload = cast(str, outputs[-1]["output"])
    assert json.loads(output_payload) == {
        "exit_code": 0,
        "stdout": "ran echo hi",
        "stderr": "",
        "timed_out": False,
    }

    await client.close()


@pytest.mark.asyncio
async def test_agent_yield_control(settings: OpenAISettings, history: ConversationHistory) -> None:
    response = _response_with_tool_call(
        call_id="call-yield",
        tool_name="yield_control",
        arguments="{}",
    )
    client = _make_openai_client(settings.api_key, response)

    agent = OpenAIAgent(settings, history, client)
    await agent.handle_user_message("ready to idle")

    assert agent.waiting_for_matrix

    items = [cast(Mapping[str, object], entry) for entry in history.build_input_items(settings.system_prompt)]
    reasoning_items = [item for item in items if item.get("type") == "reasoning"]
    assert reasoning_items
    reasoning_model = ResponseReasoningItem.model_validate(reasoning_items[0])
    assert reasoning_model.encrypted_content == "ciphertext"
    assert reasoning_model.content in (None, [])
    function_outputs = [item for item in items if item.get("type") == "function_call_output"]
    assert function_outputs
    yield_payload = cast(str, function_outputs[-1]["output"])
    assert json.loads(yield_payload) == {
        "status": "waiting_for_matrix"
    }

    await client.close()


def _response_with_tool_call(call_id: str, tool_name: str, arguments: str) -> Response:
    reasoning = ResponseReasoningItem(
        id=f"reasoning-{call_id}",
        type="reasoning",
        summary=[Summary(type="summary_text", text="thinking")],
        content=None,
        encrypted_content="ciphertext",
    )

    function_call = ResponseFunctionToolCall(
        call_id=call_id,
        name=tool_name,
        arguments=arguments,
        type="function_call",
    )

    tools = cast(
        list[Tool],
        [
            FunctionTool(
                name="run_shell_command",
                description="Execute shell command.",
                parameters={
                    "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
            strict=False,
            type="function",
        ),
            FunctionTool(
                name="yield_control",
                description="Yield control to runtime loop.",
                parameters={"type": "object", "properties": {}},
                strict=False,
                type="function",
            ),
        ],
    )

    return Response(
        id=f"resp-{call_id}",
        created_at=0.0,
        model="gpt-5",
        object="response",
        output=[reasoning, function_call],
        parallel_tool_calls=False,
        tool_choice="required",
        tools=tools,
    )

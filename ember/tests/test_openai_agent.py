from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import cast

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
from ember.openai_agent import OpenAIAgent
from ember.secrets import ProjectedSecret
import ember.tools.run_shell_command as run_shell_tool
from ember.tools.run_shell_command import ShellCommandResult


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> OpenAISettings:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    return OpenAISettings(
        api_key_secret=ProjectedSecret(name="openai_api_key", env_var="OPENAI_API_KEY"),
        model="gpt-5",
        system_prompt="system prompt",
    )


@pytest.fixture
def history(tmp_path: Path) -> ConversationHistory:
    return ConversationHistory(tmp_path / "history.jsonl")


def _make_openai_client(api_key: str, responses: list[Response]) -> AsyncOpenAI:
    client = AsyncOpenAI(api_key=api_key)

    async def _create(**kwargs):  # type: ignore[no-untyped-def]
        if responses:
            return responses.pop(0)
        raise RuntimeError("Unexpected additional model request")

    client.responses.create = _create
    return client


@pytest.mark.asyncio
async def test_agent_runs_shell_command(
    monkeypatch: pytest.MonkeyPatch,
    settings: OpenAISettings,
    history: ConversationHistory,
) -> None:
    client = _make_openai_client(
        settings.api_key,
        [
            _response_with_tool_call(
                call_id="call-1",
                tool_name="run_shell_command",
                arguments='{"command": "echo hi"}',
            ),
            _response_with_tool_call(
                call_id="call-2",
                tool_name="yield_control",
                arguments="{}",
            ),
        ],
    )

    async def fake_run_command(command: str) -> ShellCommandResult:
        return ShellCommandResult(exit_code=0, stdout=f"ran {command}", stderr="")

    monkeypatch.setattr(run_shell_tool, "_run_command", fake_run_command)

    agent = OpenAIAgent(settings, history, client)
    await agent.handle_user_message("incoming message")

    assert agent.waiting_for_matrix

    items = [
        cast(Mapping[str, object], item)
        for item in history.build_input_items(settings.system_prompt)
    ]
    reasoning_items = [item for item in items if item.get("type") == "reasoning"]
    assert reasoning_items
    reasoning_model = ResponseReasoningItem.model_validate(reasoning_items[0])
    assert reasoning_model.encrypted_content == "ciphertext"
    assert reasoning_model.content in (None, [])
    outputs = [item for item in items if item.get("type") == "function_call_output"]
    assert outputs
    run_command_output = next(
        payload
        for payload in (json.loads(cast(str, item["output"])) for item in outputs)
        if "exit_code" in payload
    )
    assert run_command_output == {
        "exit_code": 0,
        "stdout": "ran echo hi",
        "stderr": "",
        "timed_out": False,
    }

    await client.close()


@pytest.mark.asyncio
async def test_agent_yield_control(
    settings: OpenAISettings, history: ConversationHistory
) -> None:
    client = _make_openai_client(
        settings.api_key,
        [
            _response_with_tool_call(
                call_id="call-yield",
                tool_name="yield_control",
                arguments="{}",
            )
        ],
    )

    agent = OpenAIAgent(settings, history, client)
    await agent.handle_user_message("ready to idle")

    assert agent.waiting_for_matrix

    items = [
        cast(Mapping[str, object], entry)
        for entry in history.build_input_items(settings.system_prompt)
    ]
    reasoning_items = [item for item in items if item.get("type") == "reasoning"]
    assert reasoning_items
    reasoning_model = ResponseReasoningItem.model_validate(reasoning_items[0])
    assert reasoning_model.encrypted_content == "ciphertext"
    assert reasoning_model.content in (None, [])
    function_outputs = [
        item for item in items if item.get("type") == "function_call_output"
    ]
    assert function_outputs
    yield_payload = cast(str, function_outputs[-1]["output"])
    assert json.loads(yield_payload) == {"status": "waiting_for_matrix"}

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

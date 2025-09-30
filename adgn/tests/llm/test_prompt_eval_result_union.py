from pathlib import Path

import pytest

from adgn.mcp.inproc_transport import make_inproc_slot_spec
from adgn.agent.mcp_manager import McpManager
from adgn.props.critic import CriticSubmitPayload
import adgn.props.prompt_eval.server as pe
from adgn.props.prompt_eval.server import build_server

from .support.openai_mock import LIVE  # sentinel for live client
from adgn.openai_utils.model import (
    ResponsesRequest,
)
from tests.fixtures.responses import (
    ResponsesFactory,
)  # single factory for adapter responses


# Behavior (mock): our Pydantic request; return our Pydantic ResponsesResult
async def _behavior_ok(req):
    assert isinstance(req, ResponsesRequest), f"unexpected request type: {type(req)!r}"
    rf = ResponsesFactory("gpt-5-nano")

    # If grader tools are offered, simulate a function_call to submit_result
    tools = req.tools
    if isinstance(tools, list):
        names: list[str] = []
        for t in tools:
            if isinstance(t, dict) and isinstance(t.get("name"), str):
                names.append(t["name"])  # exact key access
        if any(
            n in ("grader_submit__submit_result", "mcp__grader_submit__submit_result")
            for n in names
        ):
            args = {
                "result": {
                    "true_positive_ids": [],
                    "false_positive_ids": [],
                    "unknown_critique_ids": [],
                    "precision": 1.0,
                    "recall": 1.0,
                    "message_md": "ok",
                }
            }
            return rf.make(rf.tool_call("mcp__grader_submit__submit_result", args))

    # Otherwise: critic path → simple assistant text
    inp = req.input
    text = "ok"
    if isinstance(inp, str):
        if inp == "foo":
            text = "ok-foo"
        elif inp == "discover":
            text = "ok-discover"
    return rf.make_assistant_message(text)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "openai_client_param",
    [
        pytest.param(_behavior_ok, id="mock"),
        pytest.param(LIVE, id="live", marks=pytest.mark.live_llm),
    ],
    indirect=True,
)
async def test_prompt_eval_returns_failure_on_critic_error(
    openai_client_param, tmp_path: Path
) -> None:
    # Build server with provided client (mock/live)
    mcp_server, _state = build_server(
        client=openai_client_param, name="prompt_eval_test", run_dir_base=tmp_path
    )

    # Patch _run_critic_for_specimen to raise within the server module
    async def _fake(
        specimen, system_prompt, client, run_dir, *, agent_model="gpt-5", **kwargs
    ):
        raise RuntimeError("simulated critic failure")

    pe._run_critic_for_specimen = _fake
    # Limit to one real specimen to keep test deterministic and fast while exercising real data
    pe.list_specimen_names = lambda base: ["2025-09-02-ducktape_wt"]

    async with McpManager(
        {"prompt_eval_test": make_inproc_slot_spec(mcp_server)},
    ) as mcp:
        res = await mcp.call_tool_typed(
            "prompt_eval_test",
            "test_prompt",
            {"prompt": "dummy"},
            pe.PromptEvalResult,
        )
        assert isinstance(res, pe.PromptEvalFailure), (
            f"expected PromptEvalFailure, got {type(res)!r}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "openai_client_param",
    [
        pytest.param(_behavior_ok, id="mock"),
        pytest.param(LIVE, id="live", marks=pytest.mark.live_llm),
    ],
    indirect=True,
)
async def test_prompt_eval_returns_success_on_all_ok(
    openai_client_param, tmp_path: Path
) -> None:
    # Build server with provided client (mock/live)
    mcp_server, _state = build_server(
        client=openai_client_param, name="prompt_eval_test2", run_dir_base=tmp_path
    )

    # Patch _run_critic_for_specimen to return a minimal CriticSubmitPayload instance
    async def _fake_ok(
        specimen,
        system_prompt,
        client,
        run_dir,
        *,
        agent_model="gpt-5",
        **kwargs,
    ):
        return CriticSubmitPayload(issues=[], notes_md=None)

    pe._run_critic_for_specimen = _fake_ok
    # Limit to one real specimen for a focused test run
    pe.list_specimen_names = lambda base: ["2025-09-02-ducktape_wt"]

    async with McpManager(
        {"prompt_eval_test2": make_inproc_slot_spec(mcp_server)},
    ) as mcp:
        res = await mcp.call_tool_typed(
            "prompt_eval_test2",
            "test_prompt",
            {"prompt": "dummy"},
            pe.PromptEvalResult,
        )
        assert isinstance(res, pe.PromptEvalSuccess), (
            f"expected PromptEvalSuccess, got {type(res)!r}"
        )

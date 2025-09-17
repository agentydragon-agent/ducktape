from pathlib import Path

import pytest

from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mini_codex.mcp_manager import McpManager
from adgn.llm.properties.critic import CriticSubmitPayload
import adgn.llm.properties.prompt_eval.server as pe
from adgn.llm.properties.prompt_eval.server import build_server

from .support.openai_builders import (
    make_assistant_text_response,
    make_function_call_response,
)
from .support.openai_mock import LIVE  # sentinel for live client


# Behavior (mock): typed request, big switch on structured fields, real SDK model returned
async def _behavior_ok(req):
    # Strong shape: treat request as dict (Responses.create params are TypedDict at runtime)
    assert isinstance(req, dict), f"unexpected request type: {type(req)!r}"

    # If grader tools are offered, simulate a function_call to submit_result
    tools = req.get("tools")
    if isinstance(tools, list):
        names: list[str] = []
        for t in tools:
            if isinstance(t, dict) and isinstance(t.get("name"), str):
                names.append(t["name"])  # exact key access (no getattr)
        if any(
            n in ("grader_submit__submit_result", "mcp__grader_submit__submit_result")
            for n in names
        ):
            args = (
                '{"result": {"true_positive_ids": [], "false_positive_ids": [], '
                '"unknown_critique_ids": [], "precision": 1.0, "recall": 1.0, "message_md": "ok"}}'
            )
            return make_function_call_response(
                tool_name="mcp__grader_submit__submit_result",
                arguments_json=args,
                request=None,
            )

    # Otherwise: critic path → simple assistant text
    inp = req.get("input")
    assert (inp is None) or isinstance(inp, str), (
        f"input must be str|None, got {type(inp)!r}"
    )
    if inp == "foo":
        return make_assistant_text_response(text="ok-foo")
    if inp == "discover":
        return make_assistant_text_response(text="ok-discover")
    return make_assistant_text_response(text="ok")


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
        client=openai_client_param, name="prompt_eval_test"
    )

    # Patch _run_critic_for_specimen to raise within the server module
    async def _fake(specimen, system_prompt, client, run_dir, *, agent_model="gpt-5"):
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
        client=openai_client_param, name="prompt_eval_test2"
    )

    # Patch _run_critic_for_specimen to return a minimal CriticSubmitPayload instance
    async def _fake_ok(
        specimen,
        system_prompt,
        client,
        run_dir,
        *,
        agent_model="gpt-5",
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

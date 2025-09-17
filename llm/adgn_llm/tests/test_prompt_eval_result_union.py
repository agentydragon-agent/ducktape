from pathlib import Path

import adgn_llm.properties.prompt_eval.server as pe
import pytest
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mini_codex.mcp_manager import McpManager
from adgn_llm.properties.critic import CriticSubmitPayload
from adgn_llm.properties.prompt_eval.server import build_server


@pytest.mark.asyncio
async def test_prompt_eval_returns_failure_on_critic_error(tmp_path: Path) -> None:
    # Build server
    mcp_server, _state = build_server(name="prompt_eval_test")

    # Patch _run_critic_for_specimen to raise within the server module
    async def _fake(specimen, system_prompt, client, run_dir, *, agent_model="gpt-5"):
        raise RuntimeError("simulated critic failure")

    pe._run_critic_for_specimen = _fake
    # Limit to one real specimen to keep test deterministic and fast while exercising real data
    pe.list_specimen_names = lambda base: ["2025-09-02-ducktape_wt"]

    async with McpManager({"prompt_eval_test": make_inproc_slot_spec(mcp_server)}) as mcp:
        res = await mcp.call_tool_typed("prompt_eval_test", "test_prompt", {"prompt": "dummy"}, pe.PromptEvalResult)
        assert isinstance(res, pe.PromptEvalFailure), f"expected PromptEvalFailure, got {type(res)!r}"


@pytest.mark.asyncio
async def test_prompt_eval_returns_success_on_all_ok(tmp_path: Path) -> None:
    # Build server
    mcp_server, _state = build_server(name="prompt_eval_test2")

    # Patch _run_critic_for_specimen to return a minimal CriticSubmitPayload-like dict
    async def _fake_ok(specimen, system_prompt, client, run_dir, *, agent_model="gpt-5"):
        # return a minimal CriticSubmitPayload instance so downstream grading code can call model_dump_json()

        return CriticSubmitPayload(issues=[], notes_md=None)

    pe._run_critic_for_specimen = _fake_ok
    # Limit to one real specimen for a focused test run
    pe.list_specimen_names = lambda base: ["2025-09-02-ducktape_wt"]

    async with McpManager({"prompt_eval_test2": make_inproc_slot_spec(mcp_server)}) as mcp:
        res = await mcp.call_tool_typed("prompt_eval_test2", "test_prompt", {"prompt": "dummy"}, pe.PromptEvalResult)
        assert isinstance(res, pe.PromptEvalSuccess), f"expected PromptEvalSuccess, got {type(res)!r}"

import json
import time
from pathlib import Path

import pytest
from adgn_llm.instruction_optimizer.config import (
    DebugConfig,
    GraderConfig,
    OptimizerConfig,
    PromptEngineerConfig,
    RolloutConfig,
    SummarizerConfig,
    TokenConfig,
    TruncationConfig,
)
from adgn_llm.instruction_optimizer.engine import optimizer as opt
from adgn_llm.instruction_optimizer.engine.models import (
    AgentTaskType,
    Criterion,
    MessageBasedGrading,
    TaskDefinition,
    TaskType,
)
from adgn_llm.instruction_optimizer.io.jsonl_logger import JSONLLogger
from openai.types.responses import Response
from openai.types.responses.response_function_tool_call_item import (
    ResponseFunctionToolCallItem,
)
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText


def mk_func_call(
    *,
    name: str,
    args: dict,
    call_id: str,
    id: str | None = None,
) -> ResponseFunctionToolCallItem:
    return ResponseFunctionToolCallItem(
        id=id or call_id,
        type="function_call",
        name=name,
        arguments=json.dumps(args),
        call_id=call_id,
    )


def mk_msg(text: str, *, id: str = "msg-1") -> ResponseOutputMessage:
    return ResponseOutputMessage(
        id=id,
        type="message",
        role="assistant",
        status="completed",
        content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
    )


def mk_response(
    output: list,
    *,
    model: str,
    id: str | None = None,
    tools: list | None = None,
    tool_choice: str | dict | None = None,
    parallel_tool_calls: bool = False,
) -> Response:
    return Response(
        id=id or f"resp-{int(time.time() * 1000)}",
        object="response",
        model=model,
        created_at=int(time.time()),
        output=output,
        tools=tools or [],
        tool_choice=tool_choice or "auto",
        parallel_tool_calls=parallel_tool_calls,
    )


class FakeResponsesAPI:
    """Async responses API that returns real Pydantic type objects for Responses."""

    def __init__(self):
        self._pe_counter = 0

    async def create(self, model, **kwargs):
        tools = kwargs.get("tools", [])
        tool_choice = kwargs.get("tool_choice")
        previous_response_id = kwargs.get("previous_response_id")
        # Prioritize tool_choice based routing
        if tool_choice and isinstance(tool_choice, dict):
            name = tool_choice.get("name")
            # PromptEngineer submit_prompt path
            if name == "submit_prompt":
                self._pe_counter += 1
                call = mk_func_call(
                    name="submit_prompt",
                    args={"prompt": f"PROMPT_V{self._pe_counter}"},
                    call_id=f"pe-{self._pe_counter}",
                    id=f"call-{self._pe_counter}",
                )
                return mk_response(
                    [call],
                    model=model,
                    tools=tools,
                    tool_choice=tool_choice,
                )
            # Grader submit_grades path
            if name == "submit_grades":
                # Find required keys from tool schema
                required = []
                if tools:
                    tool = tools[0]
                    params = tool.get("parameters", {})
                    required = params.get("required", [])
                payload = {rk: {"score": 9.0, "rationale": "ok"} for rk in required}
                call = mk_func_call(
                    name="submit_grades",
                    args=payload,
                    call_id="grade-1",
                    id="call-grade",
                )
                return mk_response(
                    [call],
                    model=model,
                    tools=tools,
                    tool_choice=tool_choice,
                )
            # Comparison grading (not exercised here)
        # MiniCodexRunner flow
        # First turn forces tool_choice="required" with tools including shell_run
        if tool_choice == "required":
            call = mk_func_call(
                name="shell_run",
                args={
                    "cmd": ["bash", "-lc", "echo runner_ok > result.txt"],
                    "timeout_ms": 2000,
                },
                call_id="shell-1",
                id="call-shell-1",
            )
            return mk_response(
                [call],
                model=model,
                tools=tools,
                tool_choice=tool_choice,
            )
        # Subsequent turn after tool outputs: return assistant message
        if previous_response_id is not None:
            return mk_response(
                [mk_msg("done", id="msg-1")],
                model=model,
                tools=tools,
                tool_choice=tool_choice,
            )
        # Default: assistant text (shouldn't be used in our paths)
        raise Exception("unhandled call of mock")


class FakeAsyncOpenAI:
    def __init__(self, *a, **k):
        self.responses = FakeResponsesAPI()


@pytest.fixture
def cfg_two_iters() -> OptimizerConfig:
    return OptimizerConfig(
        seeds_file="seeds.yaml",
        graders_file="graders.yaml",
        rollouts=RolloutConfig(max_parallel=1, max_turns=2, bash_timeout_ms=10_000),
        prompt_engineer=PromptEngineerConfig(
            model="gpt-4o-mini",
            reasoning_effort="low",
            feedback_mode="full_rollouts",
        ),
        grader=GraderConfig(model="gpt-4o-mini", reasoning_effort="low"),
        summarizer=SummarizerConfig(model="gpt-4o-mini", max_tokens=512),
        tokens=TokenConfig(
            max_response_tokens=512,
            reasoning_buffer_tokens=256,
            max_context_tokens=200_000,
            max_files_tokens=4096,
        ),
        truncation=TruncationConfig(
            max_file_size_grading=8192,
            max_file_size_pattern_analysis=8192,
            log_message_length=2048,
        ),
        debug=DebugConfig(enable_strace=False),
        exclude_patterns=["*.bin", "*.min.js"],
        wrapper_env={},
    )


@pytest.mark.asyncio
async def test_optimize_prompts_two_iterations_async(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cfg_two_iters: OptimizerConfig,
):
    # Patch AsyncOpenAI everywhere to use our fake
    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeAsyncOpenAI)

    base_dir = tmp_path / "run"
    base_dir.mkdir(parents=True, exist_ok=True)

    # Task and configs
    seed_tasks = [
        TaskDefinition(
            id="t1",
            prompt="print hello",
            type="coding",
            grading_overrides=MessageBasedGrading(
                criteria=[Criterion(name="overall", description="overall quality")],
            ),
        ),
    ]
    criteria = [Criterion(name="overall", description="overall quality")]
    task_types = {"coding": TaskType(name="coding", grading=None)}
    runner_configs = {
        "claude": {"type": "minicodex_runner", "config": {"model": "o4-mini"}},
    }

    # Logging client using fake AsyncOpenAI
    dummy_client = opt.LoggingOpenAIClient(
        openai_client=FakeAsyncOpenAI(),
        jsonl_logger=JSONLLogger(base_dir / "api.jsonl"),
    )

    # Ensure logging is initialized for optimizer
    opt.DualOutputLogging.setup_logging(verbose=False)
    opt.logger = opt.DualOutputLogging.get_logger()

    # Disable plotting by stubbing tracker.generate_report
    orig_generate_report = opt.ScoreEvolutionTracker.generate_report

    def _no_plot(self, run_dir, log_path):
        return "report"

    monkeypatch.setattr(opt.ScoreEvolutionTracker, "generate_report", _no_plot)

    out_dir = await opt.optimize_prompts(
        anthropic_log=JSONLLogger(base_dir / "anthropic.jsonl"),
        openai_client=dummy_client,
        seed_tasks=seed_tasks,
        criteria=criteria,
        cfg=cfg_two_iters,
        runner_name="claude",
        task_types=task_types,
        runner_configs=runner_configs,
        task_type=AgentTaskType.CODING,
        iterations=2,
        rollouts_per_task=1,
        max_parallel_rollouts=1,
        tasks_per_iteration=1,
        base_dir=base_dir,
    )

    # Iteration prompts
    iter1 = out_dir / "iter_001" / "CLAUDE.md"
    iter2 = out_dir / "iter_002" / "CLAUDE.md"
    assert iter1.exists() and iter2.exists()
    assert iter1.read_text().startswith("PROMPT_V1")
    assert iter2.read_text().startswith("PROMPT_V2")

    # Artifacts for both iterations
    for i in (1, 2):
        rollout_dir = out_dir / f"iter_{i:03d}" / "t1" / "agent_0"
        assert (rollout_dir / "rollout.json").exists()
        assert (rollout_dir / "grading.json").exists()
        grading = json.loads((rollout_dir / "grading.json").read_text())
        assert grading["overall_score"] == pytest.approx(9.0, rel=1e-6)

    # prompts.json should include 0 and 2 (initial + second iteration)
    prompts = json.loads((out_dir / "prompts.json").read_text())
    assert set(prompts.keys()) == {"0", "2"}
    assert prompts["2"].startswith("PROMPT_V2")

    # Restore original method
    monkeypatch.setattr(
        opt.ScoreEvolutionTracker,
        "generate_report",
        orig_generate_report,
    )

import json
from pathlib import Path

import pytest

from adgn.inop.config import (
    DebugConfig,
    GraderConfig,
    OptimizerConfig,
    PromptEngineerConfig,
    RolloutConfig,
    SummarizerConfig,
    TokenConfig,
    TruncationConfig,
)
from adgn.inop.engine.models import (
    AgentTaskType,
    AssistantMessage as TrMsg,
    Criterion,
    MessageBasedGrading,
    Rollout,
    RunnerEnvironment,
    TaskDefinition,
    TaskType,
)
import adgn.inop.engine.optimizer
import adgn.inop.engine.runner_factory
from adgn.inop.io.jsonl_logger import JSONLLogger
from adgn.inop.runners.base import AgentRunner
from adgn.openai_utils.model import (
    FunctionCallItem,
    FunctionToolParam,
    ResponsesRequest,
)


def mk_func_call(*, name: str, args: dict, call_id: str) -> FunctionCallItem:
    return FunctionCallItem(
        name=name,
        arguments=json.dumps(args),
        call_id=call_id,
    )


class FakeModelLayer:
    """Protocol-level fake model used via DI factory (make_model)."""

    def __init__(self, rf) -> None:
        self._pe_counter = 0
        self.context_window_tokens = 200000
        self._rf = rf

    async def responses_create(self, req: ResponsesRequest):
        # Access typed fields directly (no getattr duck-typing)
        tool_choice = req.tool_choice
        tools = req.tools or []

        def _tool_name(choice):
            return getattr(choice, "name", None)

        name = _tool_name(tool_choice)
        # Tool-based routing
        if name is not None:
            if name == "submit_prompt":
                self._pe_counter += 1
                call = mk_func_call(
                    name="submit_prompt",
                    args={"prompt": f"PROMPT_V{self._pe_counter}"},
                    call_id=f"pe-{self._pe_counter}",
                )
                return self._rf.make(
                    self._rf.tool_call(
                        call_id=call.call_id,
                        name=call.name,
                        arguments=json.loads(call.arguments or "{}"),
                    )
                )
            if name == "submit_grades":
                assert all(isinstance(t, FunctionToolParam) for t in tools)
                required = []
                if tools:
                    tool: FunctionToolParam = tools[0]
                    params = tool.parameters or {}
                    required = params.get("required", [])
                payload = {rk: {"score": 9.0, "rationale": "ok"} for rk in required}
                call = mk_func_call(
                    name="submit_grades",
                    args=payload,
                    call_id="grade-1",
                )
                return self._rf.make(
                    self._rf.tool_call(
                        call_id=call.call_id,
                        name=call.name,
                        arguments=payload,
                    )
                )
        # When tool is required: emit propose_prompt in outer loop; inner (runner) returns text
        if tool_choice == "required":
            # Always propose a prompt when tool is required (outer PE agent)
            self._pe_counter += 1
            call = mk_func_call(
                name="mcp__prompt_feedback__propose_prompt",
                args={"prompt": f"PROMPT_V{self._pe_counter}"},
                call_id=f"pe-{self._pe_counter}",
            )
            return self._rf.make(
                self._rf.tool_call(
                    call_id=call.call_id,
                    name=call.name,
                    arguments={"prompt": f"PROMPT_V{self._pe_counter}"},
                )
            )
        # Default assistant text
        return self._rf.make_assistant_message("default")


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
    responses_factory,
):
    # Provide a lightweight runner that avoids Docker and writes deterministic outputs
    class FakeRunner(AgentRunner):
        async def setup(self, task: TaskDefinition, task_type_config: dict) -> None:  # noqa: D401
            self._env = RunnerEnvironment(type="workspace_dir", data={"path": str(tmp_path / "ws")})
            (tmp_path / "ws").mkdir(parents=True, exist_ok=True)

        async def run_task(self, task: TaskDefinition, agent_instructions: str) -> Rollout:  # noqa: D401
            traj = [TrMsg(text="default")]
            files = {"README.md": f"prompt: {agent_instructions}"}
            return Rollout(
                task_id=task.id,
                runner_id=self.runner_id,
                agent_id="agent_0",
                trajectory=traj,
                files=files,
                success=True,
                duration_seconds=0.01,
            )

        async def cleanup(self) -> None:  # noqa: D401
            return None

        def get_environment(self) -> RunnerEnvironment | None:  # noqa: D401
            return getattr(self, "_env", None)

    def _fake_create_runner(runner_name: str, runner_configs: dict, openai_model=None):
        return FakeRunner(
            runner_id=runner_name,
            config=runner_configs.get(runner_name, {}).get("config", {}),
        )

    monkeypatch.setattr(adgn.inop.engine.runner_factory, "create_runner", _fake_create_runner)
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
    runner_configs = {"claude": {"type": "claude_runner", "config": {}}}

    fake_model = FakeModelLayer(responses_factory)

    # Ensure logging is initialized for optimizer
    adgn.inop.engine.optimizer.DualOutputLogging.setup_logging(verbose=False)
    adgn.inop.engine.optimizer.logger = adgn.inop.engine.optimizer.DualOutputLogging.get_logger()

    # Disable plotting by stubbing tracker.generate_report
    orig_generate_report = adgn.inop.engine.optimizer.ScoreEvolutionTracker.generate_report

    def _no_plot(self, run_dir, log_path):
        return "report"

    monkeypatch.setattr(
        adgn.inop.engine.optimizer.ScoreEvolutionTracker, "generate_report", _no_plot
    )
    monkeypatch.setenv("DUCK_ALLOW_UNSANDBOXED", "1")

    out_dir = await adgn.inop.engine.optimizer.optimize_prompts(
        adgn.inop.engine.optimizer.OptimizeArgs(
            anthropic_log=JSONLLogger(base_dir / "anthropic.jsonl"),
            pe_model=fake_model,
            runner_model=fake_model,
            grader_model=fake_model,
            summarizer_model=fake_model,
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
    )

    # Iteration prompts
    iter1 = out_dir / "iter_001" / "CLAUDE.md"
    iter2 = out_dir / "iter_002" / "CLAUDE.md"
    assert iter1.exists()
    assert iter2.exists()
    assert iter1.read_text().strip()
    assert iter2.read_text().strip()

    # Artifacts for both iterations
    for i in (1, 2):
        rollout_dir = out_dir / f"iter_{i:03d}" / "t1" / "agent_0"
        assert (rollout_dir / "rollout.json").exists()
        assert (rollout_dir / "grading.json").exists()
        grading = json.loads((rollout_dir / "grading.json").read_text())
        assert grading["overall_score"] == pytest.approx(9.0, rel=1e-6)

    # prompts.json is a list of prompts per iteration (1-based). Expect two entries for two iterations.
    prompts = json.loads((out_dir / "prompts.json").read_text())
    assert isinstance(prompts, list)
    assert len(prompts) == 2
    assert isinstance(prompts[0], str)
    assert prompts[0].strip()
    assert isinstance(prompts[1], str)
    assert prompts[1].strip()

    # Restore original method
    monkeypatch.setattr(
        adgn.inop.engine.optimizer.ScoreEvolutionTracker, "generate_report", orig_generate_report
    )

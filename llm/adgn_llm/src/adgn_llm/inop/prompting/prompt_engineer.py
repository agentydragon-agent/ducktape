from __future__ import annotations

import math
import statistics
from contextlib import AsyncExitStack
from enum import Enum
from typing import Any, Protocol


from adgn_llm.inop.clients.logging_openai_client import (
    LoggingOpenAIModel,
)
from adgn_llm.inop.engine.models import AgentTaskType, GradedRollout
from adgn_llm.inop.io.logging_utils import DualOutputLogging
from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.mcp_manager import McpManager

logger = DualOutputLogging.get_logger()

SUBMIT_PROMPT_FUNCTION_NAME = "submit_prompt"


class FeedbackMode(Enum):
    """Processing mode for prompt optimization."""

    FULL_ROLLOUTS = "full_rollouts"
    SUMMARY = "summary"
    STATS_ONLY = "stats_only"


class FeedbackProvider(Protocol):
    async def provide_feedback(self, rollouts: list[GradedRollout]) -> str:
        """Provide feedback string based on a batch of rollouts."""
        ...

    def verbal_description(self) -> str:
        """Return a human-language description of the feedback provider."""
        ...


class FullRolloutsFeedbackProvider(FeedbackProvider):
    async def provide_feedback(self, rollouts: list[GradedRollout]) -> str:
        summaries: list[str] = []
        for graded_code in rollouts:
            # Use Pydantic's model_dump_json which will use our custom serializers
            summary = graded_code.model_dump_json(indent=2)
            summaries.append(summary)
        return "\n\n".join(summaries)

    def verbal_description(self) -> str:
        return "Full rollouts feedback provider, providing full task rollouts with messages and tool use."


class StatsOnlyFeedbackProvider(FeedbackProvider):
    async def provide_feedback(self, rollouts: list[GradedRollout]) -> str:
        """Provide feedback string based on a batch of rollouts."""
        assert len(rollouts) >= 2
        overall_scores = [graded_code.grade.overall_score for graded_code in rollouts]
        n = len(overall_scores)
        mean_score = sum(overall_scores) / n
        std_err = statistics.stdev(overall_scores) / math.sqrt(n)
        return f"Mean overall score: {mean_score:.2f} (standard error {std_err:.2f})"

    def verbal_description(self) -> str:
        return "Mean overall score (point estimate and 95% CI)"


class PromptEngineer:
    def __init__(
        self,
        model: LoggingOpenAIModel,
        feedback_provider: FeedbackProvider,
        task_type: AgentTaskType = AgentTaskType.CODING,
    ) -> None:
        self.model = model
        self.feedback_provider = feedback_provider
        self.task_type = task_type
        self._exit_stack = AsyncExitStack()
        self._prompt_agent: MiniCodex | None = None
        self._last_prompt: str | None = None

    @property
    def prompt_messages(
        self,
    ) -> list[dict[str, Any]]:
        # Determine agent type description based on task type
        if self.task_type == AgentTaskType.CODE_REVIEW:
            agent_description = "a code review agent"
            task_description = (
                "- Agent reviews code files and identifies issues, bugs, and improvements.\n"
                "- Agent has access to a filesystem and shell to examine the codebase.\n"
            )
        else:  # AgentTaskType.CODING
            agent_description = "a coding agent"
            task_description = (
                "- Agent has access to a filesystem and a shell through tools. "
                "Tasks should be solved by writing code files on disk using these tools, "
                "not just shown to user in conversation.\n"
            )

        system_message = (
            f"You are an expert LLM prompt engineer. Your task is to design the best prompt for a LLM used as "
            f"{agent_description}.\n"
            f"{task_description}"
            "- Agent has a fixed system prompt teaches it how to use its tools (and other basics).\n"
            "- Avoid giving your own instructions on how to use the tools - agent's baked-in tool use instructions "
            "are already correct and additional conflicting instructions could easily make it worse.\n"
            "- Each turn, you will propose a prompt. The agent will be run with that prompt on several tasks, "
            "and you will receive information from these rollouts to help you design a better prompt.\n"
            "- Your goal is to *find the best performing prompt you can* over *10 turns* of (propose prompt1 -> "
            "receive feedback1 -> propose prompt2 -> ...). You will be scored by the max score, not the last score.\n"
            f"- The feedback will take the form of: {self.feedback_provider.verbal_description()}\n"
        )

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_message}]

        if self._last_prompt is not None:
            messages.append(
                {
                    "role": "assistant",
                    "content": f"Previous prompt:\n{self._last_prompt}",
                },
            )

        return messages

    async def _ensure_prompt_agent(self) -> MiniCodex:
        if self._prompt_agent is None:
            # Prompt engineer currently has no MCP tools; MiniCodex still expects a manager
            # with zero slots, which behaves as a no-op for tool listing.
            self._prompt_agent = await MiniCodex.create(
                model=self.model.model,
                mcp=McpManager({}),
                client=self.model.openai_client.openai_client,
                system=None,
            )
            await self._exit_stack.enter_async_context(self._prompt_agent)
        return self._prompt_agent

    async def propose_prompt(
        self,
    ) -> str:
        agent = await self._ensure_prompt_agent()

        result = await agent.run(
            user_text="Generate an improved system prompt.",
        )

        new_prompt = result.text.strip()
        if not new_prompt:
            raise ValueError("MiniCodex did not return a prompt")

        self._last_prompt = new_prompt
        return new_prompt

    async def add_result(
        self,
        reasoning: list[Any],
        function_call_message: Any,
        proposed_prompt: str,
        rollouts: list[GradedRollout],
    ) -> None:
        feedback = await self.feedback_provider.provide_feedback(rollouts)
        logger.info(
            "Prompt feedback",
            prompt=proposed_prompt[:200],
            feedback_preview=feedback[:200],
        )
        self._last_prompt = proposed_prompt

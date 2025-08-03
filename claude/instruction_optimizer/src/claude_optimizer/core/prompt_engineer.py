from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from openai.types.responses.response import Response
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_function_tool_call_item import (
    ResponseFunctionToolCallItem,
)
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_reasoning_item import ResponseReasoningItem

from claude_optimizer.config import OptimizerConfig
from claude_optimizer.core.logging_utils import DualOutputLogging
from claude_optimizer.core.models import GradedCode

logger = DualOutputLogging.get_logger()

SUBMIT_PROMPT_FUNCTION_NAME = "submit_prompt"


@dataclass
class Turn:
    reasoning: list[ResponseOutputMessage | ResponseReasoningItem]
    function_call_message: ResponseFunctionToolCall | ResponseFunctionToolCallItem
    proposed_prompt: str
    feedback: dict[str, Any]

    @property
    def messages(self) -> list[dict[str, Any]]:
        msgs: list[dict[str, Any]] = []
        for reasoning_item in self.reasoning:
            msg_dict = reasoning_item.model_dump()
            if "status" in msg_dict:
                del msg_dict["status"]
            msgs.append(msg_dict)
        function_call_dict = self.function_call_message.model_dump()
        if "status" in function_call_dict:
            del function_call_dict["status"]
        msgs.append(function_call_dict)
        msgs.append(
            {
                "type": "function_call_output",
                "call_id": self.function_call_message.call_id,
                "output": self.feedback,
            },
        )
        return msgs


class FeedbackMode(Enum):
    """Processing mode for prompt optimization."""

    FULL_ROLLOUTS = "full_rollouts"
    SUMMARY = "summary"
    STATS_ONLY = "stats_only"


class FeedbackProvider(Protocol):
    async def provide_feedback(self, rollouts: list[GradedCode]) -> str:
        """Provide feedback string based on a batch of rollouts."""
        ...

    def verbal_description(self) -> str:
        """Return a human-language description of the feedback provider."""
        ...


class FullRolloutsFeedbackProvider(FeedbackProvider):
    async def provide_feedback(self, rollouts: list[GradedCode]) -> str:
        summaries: list[str] = []
        for graded_code in rollouts:
            message_lines = [
                json.dumps(evt) for evt in graded_code.code_result.messages
            ]
            files_json = json.dumps(graded_code.code_result.files, indent=2)
            axis_parts: list[str] = []
            for axis_name, score_with_rationale in graded_code.grade.axes.items():
                axis_parts.append(
                    f"  {axis_name}: {score_with_rationale.score}/10 - {score_with_rationale.rationale}",
                )
            summary = (
                f"Task: {graded_code.code_result.task}\n"
                f"Overall Grade: {graded_code.grade.overall_score}\n"
                f"Axes:\n{chr(10).join(axis_parts)}\n"
                f"Files:\n{files_json}\n"
                f"Full Messages:\n{chr(10).join(message_lines)}"
            )
            summaries.append(summary)
        return "\n\n".join(summaries)

    def verbal_description(self) -> str:
        return "Full rollouts feedback provider, providing full task rollouts with messages and tool use."


class StatsOnlyFeedbackProvider(FeedbackProvider):
    async def provide_feedback(self, rollouts: list[GradedCode]) -> str:
        """Provide feedback string based on a batch of rollouts."""
        assert len(rollouts) > 1
        overall_scores = [graded_code.grade.overall_score for graded_code in rollouts]
        mean_score = sum(overall_scores) / len(overall_scores)
        std_err = statistics.stdev(overall_scores) / math.sqrt(n)
        return f"Mean overall score: {mean_score:.2f} (standard error {std_err:.2f})"

    def verbal_description(self) -> str:
        return "Mean overall score (point estimate and 95% CI)"


class PromptEngineer:
    def __init__(
        self,
        model: LoggingOpenAIModel,
        feedback_provider: FeedbackProvider,
    ) -> None:
        self.model = model
        self._turns: list[Turn] = []
        self.feedback_provider = feedback_provider

    @property
    def prompt_messages(
        self,
    ) -> list[
        dict[str, Any]
        | ResponseOutputMessage
        | ResponseReasoningItem
        | ResponseFunctionToolCall
        | ResponseFunctionToolCallItem
    ]:
        system_message = (
            f"You are an expert LLM prompt engineer. Your task is to design the best prompt for a LLM used as a coding agent.\n"
            "- Agent has access to a filesystem and a shell through tools. Tasks should be solved by writing code files on disk using these tools, not just shown to user in conversation.\n"
            "- Agent has a fixed system prompt teaches it how to use its tools (and other basics).\n"
            "- Avoid giving your own instructions on how to use the tools - agent's baked-in tool use instructions are already correct and additional conflicting instructions could easily make it worse.\n"
            "- Each turn, you will propose a prompt. The agent will be run with that prompt on several tasks, and you will receive information from these rollouts to help you design a better prompt.\n"
            "- Your goal is to *find the best performing prompt you can* over *10 turns* of (propose prompt1 -> receive feedback1 -> propose prompt2 -> ...). You will be scored by the max score, not the last score.\n"
            f"- The feedback will take the form of: {self.feedback_provider.verbal_description()}\n"
        )

        messages: list[
            dict[str, Any]
            | ResponseOutputMessage
            | ResponseReasoningItem
            | ResponseFunctionToolCall
            | ResponseFunctionToolCallItem
        ] = [{"role": "system", "content": system_message}]

        for turn in self._turns:
            messages.extend(turn.messages)

        return messages

    def _count_message_tokens(self, m) -> int:
        # xxx todo: very rough
        if hasattr(m, "model_dump"):
            return self.model.count_tokens(str(m.model_dump()))
        return self.model.count_tokens(str(m))

    @property
    def prompt_token_count(self) -> int:
        return sum(self._count_message_tokens(msg) for msg in self.prompt_messages)

    def _trim_context_if_needed(self) -> None:
        # TODO: trim context
        if self.prompt_token_count >= self.model.context_window_tokens:
            raise NotImplementedError()

    async def propose_prompt(
        self,
    ) -> tuple[
        list[ResponseOutputMessage | ResponseReasoningItem],
        ResponseFunctionToolCall | ResponseFunctionToolCallItem,
        str,
    ]:
        self._trim_context_if_needed()

        tools = [
            {
                "type": "function",
                "name": SUBMIT_PROMPT_FUNCTION_NAME,
                "description": "Submit an improved system prompt",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "The improved system prompt",
                        },
                    },
                    "required": ["prompt"],
                },
            },
        ]

        response: Response = self.model.responses_create(
            messages=self.prompt_messages,
            tools=tools,
            tool_use={"type": "function", "name": SUBMIT_PROMPT_FUNCTION_NAME},
        )
        reasoning_messages: list[ResponseOutputMessage | ResponseReasoningItem] = []
        function_call_item: (
            ResponseFunctionToolCall | ResponseFunctionToolCallItem | None
        ) = None

        for item in response.output:
            if isinstance(
                item,
                (ResponseFunctionToolCall, ResponseFunctionToolCallItem),
            ):
                function_call_item = item
            elif isinstance(item, (ResponseOutputMessage, ResponseReasoningItem)):
                reasoning_messages.append(item)

        if function_call_item is None:
            raise RuntimeError("No function_call found in response")

        call_name = function_call_item.name
        arguments_str = function_call_item.arguments

        if call_name != SUBMIT_PROMPT_FUNCTION_NAME:
            raise RuntimeError(f"Unexpected function name: {call_name}")
        if not isinstance(arguments_str, str):
            raise ValueError(f"Invalid arguments format: {arguments_str}")

        args_dict = json.loads(arguments_str)
        claude_prompt = args_dict.get("prompt", "").strip()
        if not claude_prompt:
            raise ValueError("Empty prompt returned")

        logger.info(
            "Generated new prompt",
            prompt_length=len(claude_prompt),
            conversation_turns=len(self._turns),
        )

        return reasoning_messages, function_call_item, claude_prompt

    async def add_result(
        self,
        reasoning: list[ResponseOutputMessage | ResponseReasoningItem],
        function_call_message: ResponseFunctionToolCall | ResponseFunctionToolCallItem,
        proposed_prompt: str,
        rollouts: list[GradedCode],
    ) -> None:
        feedback = await self.feedback_provider.provide_feedback(rollouts)
        self._turns.append(
            Turn(
                reasoning=reasoning,
                function_call_message=function_call_message,
                proposed_prompt=proposed_prompt,
                feedback=feedback,
            )
        )
        logger.info(
            "Added turn to conversation",
            conversation_turns=len(self._turns),
            feedback_length=len(feedback),
        )

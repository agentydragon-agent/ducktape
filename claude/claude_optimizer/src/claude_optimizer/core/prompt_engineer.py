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

from claude_optimizer.core.logging_utils import DualOutputLogging
from claude_optimizer.core.models import GradedRollout, AgentTaskType

logger = DualOutputLogging.get_logger()

SUBMIT_PROMPT_FUNCTION_NAME = "submit_prompt"


@dataclass
class Turn:
    reasoning: list[ResponseOutputMessage | ResponseReasoningItem]
    function_call_message: ResponseFunctionToolCall | ResponseFunctionToolCallItem
    proposed_prompt: str
    feedback: str

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
        self._turns: list[Turn] = []
        self.feedback_provider = feedback_provider
        self.task_type = task_type

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
                "- Agent has access to a filesystem and a shell through tools. Tasks should be solved by writing code files on disk using these tools, not just shown to user in conversation.\n"
            )
        
        system_message = (
            f"You are an expert LLM prompt engineer. Your task is to design the best prompt for a LLM used as {agent_description}.\n"
            f"{task_description}"
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
        """Trim context by removing oldest complete turns if needed."""
        # When we exceed 80% of context window, trim down to 50%
        trim_threshold = int(self.model.context_window_tokens * 0.8)
        target_tokens = int(self.model.context_window_tokens * 0.5)

        if self.prompt_token_count < trim_threshold:
            return

        logger.warning(
            "Context window approaching limit, trimming oldest turns",
            current_tokens=self.prompt_token_count,
            trim_threshold=trim_threshold,
            target_tokens=target_tokens,
            context_window=self.model.context_window_tokens,
            total_turns=len(self._turns),
        )

        # Remove oldest turns until we're under the target
        # Always keep at least the most recent turn
        while len(self._turns) > 1 and self.prompt_token_count > target_tokens:
            self._turns.pop(0)
            logger.info(
                "Removed turn from context",
                remaining_turns=len(self._turns),
                current_tokens=self.prompt_token_count,
            )

        # If still over target with just one turn, we have a problem
        if self.prompt_token_count > target_tokens and len(self._turns) == 1:
            logger.error(
                "Single turn exceeds target size",
                tokens=self.prompt_token_count,
                target_tokens=target_tokens,
            )
            raise Exception("No turns left after trimming")

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
            input=self.prompt_messages,  # OpenAI Responses API uses 'input'
            tools=tools,
            tool_choice={"type": "function", "name": SUBMIT_PROMPT_FUNCTION_NAME},  # 'tool_choice' not 'tool_use'
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

        try:
            args_dict = json.loads(arguments_str)
        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse function arguments",
                arguments=arguments_str,
                error=str(e),
            )
            raise ValueError(f"Invalid JSON in function arguments: {e}")

        claude_prompt = args_dict.get("prompt", "").strip()
        if not claude_prompt:
            logger.error(
                "Empty prompt returned by model",
                args_dict=args_dict,
                conversation_turns=len(self._turns),
            )
            raise ValueError("Empty prompt returned by model")

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
        rollouts: list[GradedRollout],
    ) -> None:
        feedback = await self.feedback_provider.provide_feedback(rollouts)
        self._turns.append(
            Turn(
                reasoning=reasoning,
                function_call_message=function_call_message,
                proposed_prompt=proposed_prompt,
                feedback=feedback,
            ),
        )
        logger.info(
            "Added turn to conversation",
            conversation_turns=len(self._turns),
            feedback_length=len(feedback),
        )

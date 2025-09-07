from __future__ import annotations

import json
from dataclasses import dataclass

from adgn_llm.inop.clients.logging_openai_client import (
    LoggingOpenAIModel,
)
from adgn_llm.inop.engine.models import GradedRollout
from adgn_llm.inop.io.logging_utils import DualOutputLogging
from adgn_llm.inop.prompting.prompt_engineer import FeedbackProvider
from adgn_llm.inop.prompting.truncation_utils import (
    TruncationManager,
    extract_text_from_openai_response,
)

logger = DualOutputLogging.get_logger()


@dataclass
class PatternSummarizer(FeedbackProvider):
    model: LoggingOpenAIModel
    truncation_manager: TruncationManager
    max_file_size_pattern_analysis: int

    _SYSTEM_MESSAGE = (
        "You are a pattern analysis expert. Your job is to analyze multiple coding task rollouts with their grades "
        "and identify key patterns, trends, and insights.\n\n"
        "Given rollout results, you should:\n"
        "1. Identify common failure patterns across tasks "
        '(e.g., "broad exception handling appears in 8/10 rollouts")\n'
        "2. Spot recurring code quality issues "
        '(e.g., "missing type hints in 70% of solutions")\n'
        "3. Note architectural trends "
        '(e.g., "agents consistently choose async approaches for API tasks")\n'
        "4. Highlight grading patterns "
        '(e.g., "defensive programming scores consistently low due to exception swallowing")\n'
        "5. Extract actionable insights for prompt improvement "
        '(e.g., "current prompt doesn\'t emphasize specific exception handling")\n\n'
        "Output a concise summary focusing on the most impactful patterns that would help a prompt engineer "
        "improve the system prompt. "
        "Prioritize patterns that appear across multiple tasks and have clear connections to prompt weaknesses."
    )

    def _count_tokens(self, text: str) -> int:
        return self.truncation_manager.count_tokens(text)

    async def provide_feedback(self, rollouts: list[GradedRollout]) -> str:
        rollout_summaries: list[str] = []
        original_count = len(rollouts)

        system_tokens = self._count_tokens(self._SYSTEM_MESSAGE)
        header_text = (
            f"Analyze these {len(rollouts)} coding task rollouts and identify key patterns for prompt improvement:\n\n"
        )
        remaining_tokens = self.model.context_window_tokens - system_tokens - self._count_tokens(header_text)

        logger.info(
            "Pattern analysis context management",
            original_rollouts=original_count,
            system_tokens=system_tokens,
            remaining_tokens=remaining_tokens,
        )

        for i, graded in enumerate(rollouts):
            task_summary = f"Task {i + 1} ({graded.task.type}):\n"
            task_summary += f"  Overall Score: {graded.grade.overall_score}/10\n"
            task_summary += f"  Key Issues: {graded.grade.overall_rationale}\n"

            facet_details: list[str] = []
            for facet_name, score_with_rationale in graded.grade.axes.items():
                facet_details.append(
                    f"\n    {facet_name}: {score_with_rationale.score}/10 - {score_with_rationale.rationale}",
                )
            task_summary += f"  Facets:{''.join(facet_details)}\n"

            # Only include files for coding tasks
            if graded.rollout.files:
                # Convert files dict to list format expected by truncation manager
                files_list = [{"path": path, "content": content} for path, content in graded.rollout.files.items()]
                truncated_files = self.truncation_manager.truncate_file_content_by_size(
                    files_list,
                    self.max_file_size_pattern_analysis,
                    "pattern analysis",
                )
                task_summary += f"  Files: {json.dumps(truncated_files, indent=2)}\n"

            potential_tokens = self._count_tokens(
                "\n".join([*rollout_summaries, task_summary]),
            )
            if potential_tokens > remaining_tokens:
                removed_count = original_count - len(rollout_summaries)
                logger.warning(
                    "PATTERN ANALYSIS TRUNCATION WARNING",
                    removed_rollouts=removed_count,
                    kept_rollouts=len(rollout_summaries),
                    would_be_tokens=potential_tokens,
                    max_tokens=remaining_tokens,
                )
                break

            rollout_summaries.append(task_summary)

        analysis_prompt = header_text + "\n".join(rollout_summaries)

        final_tokens = self._count_tokens(analysis_prompt) + system_tokens
        logger.info(
            "Pattern analysis prompt prepared",
            final_tokens=final_tokens,
            included_rollouts=len(rollout_summaries),
            excluded_rollouts=original_count - len(rollout_summaries),
            context_utilization=f"{(final_tokens / self.model.context_window_tokens) * 100:.1f}%",
        )
        return extract_text_from_openai_response(
            await self.model.responses_create(
                input=[  # OpenAI Responses API uses 'input' not 'messages'
                    {"role": "system", "content": self._SYSTEM_MESSAGE},
                    {"role": "user", "content": analysis_prompt},
                ],
                tools=[],
                tool_choice="auto",
            ),
        )
        # TODO: store, log

    def verbal_description(self) -> str:
        return "Insights and summaries of common problems from the batch generated by a LLM"

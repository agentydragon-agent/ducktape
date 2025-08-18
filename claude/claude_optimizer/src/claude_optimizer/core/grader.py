from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import openai
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_function_tool_call_item import (
    ResponseFunctionToolCallItem,
)

from claude_optimizer.config import OptimizerConfig
from claude_optimizer.core.exceptions import ContextWindowExceededException
from claude_optimizer.core.logging_openai_client import LoggingOpenAIModel
from claude_optimizer.core.logging_utils import DualOutputLogging
from claude_optimizer.core.models import (
    CodeResult,
    Criterion,
    Grade,
    ScoreWithRationale,
)
from claude_optimizer.core.truncation_utils import TruncationManager

logger = DualOutputLogging.get_logger()

SUBMIT_GRADES_FUNCTION_NAME = "submit_grades"


async def grade_code(
    result: CodeResult,
    criteria: list[Criterion],
    model: LoggingOpenAIModel,
    cfg: OptimizerConfig,
) -> Grade:
    properties: dict[str, Any] = {}
    required_keys: list[str] = []
    for crit in criteria:
        properties[crit.name] = {
            "type": "object",
            "description": crit.description,
            "properties": {
                "score": {"type": "number"},
                "rationale": {"type": "string"},
            },
            "required": ["score", "rationale"],
            "additionalProperties": False,
        }
        required_keys.append(crit.name)

    properties["overall"] = {
        "type": "object",
        "description": "Overall assessment of the solution, including a score from 0 to 10 and a brief rationale.",
        "properties": {
            "score": {"type": "number"},
            "rationale": {"type": "string"},
        },
        "required": ["score", "rationale"],
        "additionalProperties": False,
    }
    required_keys.append("overall")

    grading_tool = {
        "type": "function",
        "name": SUBMIT_GRADES_FUNCTION_NAME,
        "description": (
            "Return scores and rationales for each grading facet. Evaluate the code on the specified facets and "
            "provide an overall score and rationale."
        ),
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required_keys,
            "additionalProperties": False,
        },
        "strict": True,
    }

    # Log files being sent to grader
    logger.info(
        "Files being sent to grader",
        task_id=result.task_id,
        agent_id=result.agent_id,
        file_count=len(result.files),
        files=[
            {
                "path": fi.path,
                "size": len(fi.content),
                "truncated": len(fi.content) > cfg.truncation.max_file_size_grading,
            }
            for fi in result.files
        ],
        total_content_size=sum(len(fi.content) for fi in result.files),
    )

    # Truncate files for grading to avoid context length issues
    t_mgr = TruncationManager(cfg)
    truncated_files = []
    for file_info in result.files:
        truncated_content = t_mgr.truncate_text(
            file_info.content,
            cfg.truncation.max_file_size_grading,
            "... [truncated for grading]",
        )
        truncated_files.append(
            {
                "path": file_info.path,
                "content": truncated_content,
            }
        )

    # Further truncate total files by token count
    truncated_files = t_mgr.truncate_files_by_tokens(
        truncated_files,
        cfg.tokens.max_files_tokens,
    )

    # Log after truncation
    logger.info(
        "Files after truncation for grader",
        task_id=result.task_id,
        agent_id=result.agent_id,
        file_count=len(truncated_files),
        files=[
            {
                "path": f["path"],
                "size": len(f["content"]),
            }
            for f in truncated_files
        ],
        total_content_size=sum(len(f["content"]) for f in truncated_files),
    )

    input: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are an expert programming instructor and code reviewer. For the given task and code, "
                f"evaluate the submission according to the provided facets and then call {SUBMIT_GRADES_FUNCTION_NAME} "
                "with your scores and rationales."
            ),
        },
        {
            "role": "user",
            "content": f"Task: {result.task}\n\nFiles:\n{json.dumps(truncated_files, indent=2)}",
        },
    ]

    try:
        response = model.responses_create(
            messages=input,
            tools=[grading_tool],
            tool_use={"type": "function", "name": SUBMIT_GRADES_FUNCTION_NAME},
            reasoning_effort=cfg.grader.reasoning_effort,
        )
    except openai.BadRequestError as e:
        if "context_length_exceeded" in str(e):
            logger.error(
                "Context window exceeded during grading",
                task_id=result.task_id,
                agent_id=result.agent_id,
                total_content_size=sum(len(f["content"]) for f in truncated_files),
                file_count=len(truncated_files),
                error=str(e),
            )
            raise ContextWindowExceededException(
                f"Context window exceeded for task {result.task_id}, agent {result.agent_id}: {e!s}",
                task_id=result.task_id,
                agent_id=result.agent_id,
            )
        # Re-raise other BadRequestErrors
        raise

    call: ResponseFunctionToolCall | ResponseFunctionToolCallItem | None = None
    for item in response.output:
        if (
            isinstance(item, ResponseFunctionToolCallItem)
            and item.type == "function_call"
        ) or isinstance(item, ResponseFunctionToolCall):
            call = item
            break

    assert call and call.name == SUBMIT_GRADES_FUNCTION_NAME
    assert isinstance(call.arguments, str)
    axes = {
        facet: ScoreWithRationale(
            score=data.get("score", 0),
            rationale=data.get("rationale", ""),
        )
        for facet, data in json.loads(call.arguments).items()
    }
    # TODO: log nicely
    # t_mgr = TruncationManager(cfg)
    # logger.info(
    #     "Facet graded",
    #     facet=facet_name,
    #     score=score,
    #     rationale=t_mgr.truncate_text(
    #         rationale, cfg.truncation.log_message_length, "..."
    #     ),
    # )
    return Grade(
        task=result.task,
        task_id=result.task_id,
        agent_id=result.agent_id,
        axes=axes,
        timestamp=datetime.utcnow(),
    )

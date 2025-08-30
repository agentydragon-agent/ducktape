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
            },
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
            input=input,  # OpenAI Responses API uses 'input' not 'messages'
            tools=[grading_tool],
            tool_choice={"type": "function", "name": SUBMIT_GRADES_FUNCTION_NAME},  # 'tool_choice' not 'tool_use'
            reasoning={"effort": cfg.grader.reasoning_effort} if cfg.grader.reasoning_effort else None,
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

    if not call:
        logger.error(
            "Grader model did not return expected function call",
            task_id=result.task_id,
            agent_id=result.agent_id,
            response_output=[type(item).__name__ for item in response.output],
        )
        raise RuntimeError(f"Grader model did not return expected function call for task {result.task_id}")
        
    if call.name != SUBMIT_GRADES_FUNCTION_NAME:
        logger.error(
            "Grader model returned wrong function name",
            task_id=result.task_id,
            agent_id=result.agent_id,
            expected=SUBMIT_GRADES_FUNCTION_NAME,
            actual=call.name,
        )
        raise RuntimeError(f"Grader model returned wrong function name: {call.name}")
        
    if not isinstance(call.arguments, str):
        logger.error(
            "Grader model returned non-string arguments",
            task_id=result.task_id,
            agent_id=result.agent_id,
            arguments_type=type(call.arguments).__name__,
        )
        raise RuntimeError(f"Grader model returned invalid arguments type: {type(call.arguments)}")
    
    try:
        parsed_args = json.loads(call.arguments)
    except json.JSONDecodeError as e:
        logger.error(
            "Failed to parse grader arguments as JSON",
            task_id=result.task_id,
            agent_id=result.agent_id,
            raw_arguments=call.arguments,
            error=str(e),
        )
        raise RuntimeError(f"Failed to parse grader arguments: {e}")
    
    axes = {}
    for facet, data in parsed_args.items():
        if not isinstance(data, dict):
            logger.error(
                "Grader returned invalid data for facet",
                task_id=result.task_id,
                agent_id=result.agent_id,
                facet=facet,
                data_type=type(data).__name__,
            )
            raise RuntimeError(f"Invalid data type for facet {facet}: expected dict, got {type(data)}")
            
        if "score" not in data:
            logger.error(
                "Grader missing score for facet",
                task_id=result.task_id,
                agent_id=result.agent_id,
                facet=facet,
                available_keys=list(data.keys()),
            )
            raise RuntimeError(f"Missing score for facet {facet}")
            
        if "rationale" not in data:
            logger.error(
                "Grader missing rationale for facet",
                task_id=result.task_id,
                agent_id=result.agent_id,
                facet=facet,
                available_keys=list(data.keys()),
            )
            raise RuntimeError(f"Missing rationale for facet {facet}")
            
        axes[facet] = ScoreWithRationale(
            score=data["score"],
            rationale=data["rationale"],
        )
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

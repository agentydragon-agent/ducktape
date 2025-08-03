from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_function_tool_call_item import (
    ResponseFunctionToolCallItem,
)

from claude_optimizer.config import OptimizerConfig
from claude_optimizer.core.logging_openai_client import LoggingOpenAIModel
from claude_optimizer.core.models import (
    CodeResult,
    Criterion,
    Grade,
    ScoreWithRationale,
)

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
            "description": f"{crit.description} {crit.evaluation_criteria}",
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
            "content": f"Task: {result.task}\n\nFiles:\n{json.dumps([fi.model_dump() for fi in result.files], indent=2)}",
        },
    ]

    response = model.responses_create(
        messages=input,
        tools=[grading_tool],
        tool_use={"type": "function", "name": SUBMIT_GRADES_FUNCTION_NAME},
        reasoning_effort=cfg.grader.reasoning_effort,
    )

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
            score=data.get("score", 0), rationale=data.get("rationale", "")
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

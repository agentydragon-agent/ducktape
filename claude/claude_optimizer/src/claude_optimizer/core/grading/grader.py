"""General grading system that handles different grading strategies."""

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
from claude_optimizer.core.grading.strategies import (
    ComparisonGradingStrategy,
    FileBasedGradingStrategy,
    GradingStrategy,
    MessageBasedGradingStrategy,
    create_grading_strategy,
)
from claude_optimizer.core.logging_openai_client import LoggingOpenAIModel
from claude_optimizer.core.logging_utils import DualOutputLogging
from claude_optimizer.core.models import (
    ComparisonGrading,
    Criterion,
    FileBasedGrading,
    Grade,
    GradingContext,
    MessageBasedGrading,
    Rollout,
    RunnerEnvironment,
    ScoreWithRationale,
    TaskDefinition,
)

logger = DualOutputLogging.get_logger()


async def grade_rollout(
    rollout: Rollout,
    task: TaskDefinition,
    grading_config: FileBasedGrading | ComparisonGrading | MessageBasedGrading,
    model: LoggingOpenAIModel,
    cfg: OptimizerConfig,
    environment: RunnerEnvironment | None = None,
) -> Grade:
    """Grade a rollout using the appropriate strategy.
    
    Args:
        rollout: The rollout to grade
        task: The task that was executed
        grading_config: The grading configuration (from task type or overrides)
        model: The grading model to use
        cfg: Optimizer configuration
        environment: Optional runner environment info
        
    Returns:
        Grade with scores and rationales
    """
    # Create grading context
    context = GradingContext(
        rollout=rollout,
        task=task,
        environment=environment
    )
    
    # Create the appropriate grading strategy
    # Note: We don't pass config_path since criteria are already resolved in grading_config
    strategy = create_grading_strategy(grading_config)
    
    # Collect artifacts using the strategy
    artifacts = strategy.collect_artifacts(context)
    
    # Prepare artifacts for grading (truncation, etc.)
    prepared = strategy.prepare_for_grader(artifacts, cfg)
    
    # Handle different grading types
    if isinstance(strategy, ComparisonGradingStrategy):
        # Special handling for code review comparison
        return await _grade_comparison(
            task=task,
            prepared=prepared,
            model=model,
            cfg=cfg,
            rollout=rollout
        )
    else:
        # File-based or message-based grading
        criteria = prepared.get("criteria", [])
        return await _grade_with_criteria(
            task=task,
            prepared=prepared,
            criteria=criteria,
            model=model,
            cfg=cfg,
            rollout=rollout,
            strategy=strategy
        )


async def _grade_comparison(
    task: TaskDefinition,
    prepared: dict[str, Any],
    model: LoggingOpenAIModel,
    cfg: OptimizerConfig,
    rollout: Rollout,
) -> Grade:
    """Grade by comparing agent output to reference (for code reviews).
    
    Returns a Grade with a single 'overall' axis containing the coverage percentage.
    """
    agent_output = prepared["agent_output"]
    reference = prepared["reference"]
    
    # Create comparison prompt for code review
    prompt = f"""You are tasked with comparing two code reviews to determine coverage.

Task given to the agent:
{task.prompt}

Review to grade (from agent):
{agent_output}

Reference review (expected issues):
{reference}

Analyze how many issues from the reference review were caught by the agent's review.
- Assign partial credit if the agent identifies the same issue but describes it differently
- Do NOT penalize for false positives (issues the agent found that aren't in reference)
- Focus on whether the core problem was identified, not exact wording

Return a JSON object with:
- covered_percent: percentage of reference issues caught (0-100)
- rationale: explanation of what was caught and what was missed
"""

    # Define the grading tool for comparison
    grading_tool = {
        "type": "function",
        "name": "submit_comparison_grade",
        "description": "Submit the coverage comparison results",
        "parameters": {
            "type": "object",
            "properties": {
                "covered_percent": {
                    "type": "number",
                    "description": "Percentage of reference issues caught (0-100)",
                    "minimum": 0,
                    "maximum": 100
                },
                "rationale": {
                    "type": "string",
                    "description": "Explanation of what was caught and missed"
                }
            },
            "required": ["covered_percent", "rationale"],
            "additionalProperties": False
        },
        "strict": True
    }
    
    try:
        response = model.responses_create(
            input=prompt,
            tools=[grading_tool],
            tool_choice={"type": "function", "name": "submit_comparison_grade"},
            reasoning={"effort": cfg.grader.reasoning_effort} if cfg.grader.reasoning_effort else None,
        )
    except openai.BadRequestError as e:
        if "context_length_exceeded" in str(e):
            logger.error(
                "Context window exceeded during comparison grading",
                task_id=task.id,
                agent_id=rollout.agent_id,
                error=str(e),
            )
            raise ContextWindowExceededException(
                f"Context window exceeded for task {task.id}: {e!s}",
                task_id=task.id,
                agent_id=rollout.agent_id,
            )
        raise
    
    # Extract the function call from response
    call = None
    for item in response.output:
        if (isinstance(item, ResponseFunctionToolCallItem) and item.type == "function_call") or isinstance(item, ResponseFunctionToolCall):
            call = item
            break
    
    if not call or call.name != "submit_comparison_grade":
        logger.error("Grader did not return expected comparison function call", task_id=task.id)
        raise RuntimeError("Grader did not return expected comparison function call")
    
    # Parse the grading result
    try:
        parsed = json.loads(call.arguments)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse comparison grading", task_id=task.id, error=str(e))
        raise RuntimeError(f"Failed to parse comparison grading: {e}")
    
    # Convert percentage to 0-10 scale for consistency with other grades
    score = parsed["covered_percent"] / 10.0
    
    # Create Grade object with just the overall score
    return Grade(
        task=task.prompt,
        task_id=task.id,
        agent_id=rollout.agent_id,
        axes={
            "overall": ScoreWithRationale(
                score=score,
                rationale=parsed["rationale"]
            )
        },
        timestamp=datetime.utcnow()
    )


async def _grade_with_criteria(
    task: TaskDefinition,
    prepared: dict[str, Any],
    criteria: list[Criterion],
    model: LoggingOpenAIModel,
    cfg: OptimizerConfig,
    rollout: Rollout,
    strategy: GradingStrategy,
) -> Grade:
    """Grade using specific criteria (file-based or message-based).
    
    This is the traditional grading approach with multiple criteria axes.
    """
    # Build the grading tool schema
    properties: dict[str, Any] = {}
    required_keys: list[str] = []
    
    for crit in criteria:
        properties[crit.name] = {
            "type": "object",
            "description": crit.description,
            "properties": {
                "score": {"type": "number", "minimum": 0, "maximum": 10},
                "rationale": {"type": "string"},
            },
            "required": ["score", "rationale"],
            "additionalProperties": False,
        }
        required_keys.append(crit.name)
    
    # Always include overall
    properties["overall"] = {
        "type": "object",
        "description": "Overall assessment of the solution, score from 0 to 10",
        "properties": {
            "score": {"type": "number", "minimum": 0, "maximum": 10},
            "rationale": {"type": "string"},
        },
        "required": ["score", "rationale"],
        "additionalProperties": False,
    }
    required_keys.append("overall")
    
    grading_tool = {
        "type": "function",
        "name": "submit_grades",
        "description": "Return scores and rationales for each grading criterion",
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required_keys,
            "additionalProperties": False,
        },
        "strict": True,
    }
    
    # Generate the grading prompt using the strategy
    prompt = strategy.get_grading_prompt(prepared, task)
    
    # Add criteria descriptions
    criteria_text = "\n\n".join([
        f"- {crit.name}: {crit.description}"
        for crit in criteria
    ])
    
    full_prompt = f"{prompt}\n\nGrade the solution on these criteria:\n{criteria_text}"
    
    try:
        response = model.responses_create(
            input=full_prompt,
            tools=[grading_tool],
            tool_choice={"type": "function", "name": "submit_grades"},
            reasoning={"effort": cfg.grader.reasoning_effort} if cfg.grader.reasoning_effort else None,
        )
    except openai.BadRequestError as e:
        if "context_length_exceeded" in str(e):
            logger.error(
                "Context window exceeded during criteria grading",
                task_id=task.id,
                agent_id=rollout.agent_id,
                error=str(e),
            )
            raise ContextWindowExceededException(
                f"Context window exceeded for task {task.id}: {e!s}",
                task_id=task.id,
                agent_id=rollout.agent_id,
            )
        raise
    
    # Extract the function call
    call = None
    for item in response.output:
        if (isinstance(item, ResponseFunctionToolCallItem) and item.type == "function_call") or isinstance(item, ResponseFunctionToolCall):
            call = item
            break
    
    if not call or call.name != "submit_grades":
        logger.error("Grader did not return expected grades function call", task_id=task.id)
        raise RuntimeError("Grader did not return expected grades function call")
    
    # Parse the grades
    try:
        parsed = json.loads(call.arguments)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse grades", task_id=task.id, error=str(e))
        raise RuntimeError(f"Failed to parse grades: {e}")
    
    # Build Grade object
    axes = {}
    for facet, data in parsed.items():
        axes[facet] = ScoreWithRationale(
            score=data["score"],
            rationale=data["rationale"]
        )
    
    return Grade(
        task=task.prompt,
        task_id=task.id,
        agent_id=rollout.agent_id,
        axes=axes,
        timestamp=datetime.utcnow()
    )
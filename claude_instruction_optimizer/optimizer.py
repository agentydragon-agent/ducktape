"""Parallel prompt optimization system for Claude Code agents.

Iteratively improves CLAUDE.md by running multiple agent rollouts in parallel
on seed programming tasks, grading solutions using OpenAI's Responses API (o3 model),
and using a PromptEngineer to propose improved prompts. All data is logged to JSONL
files for analysis.

Usage:
    python3 prompt_engineer_algorithm.py [--iterations N] [--rollouts-per-task N]

    --iterations N          Number of optimization iterations (default: 10)
    --rollouts-per-task N   Number of agent rollouts per seed task (default: 5)

Key Features:
* Fully parallel rollouts with semaphore-based concurrency control
* Docker containerization for isolated Claude Code agent execution
* OpenAI Responses API integration for grading and prompt engineering
* PromptEngineer class with persistent conversation state and context trimming
* Structured logging with JSON output for comprehensive tracking

Architecture:
* Claude Code agents run in isolated Docker containers for safety
* Rollouts execute in parallel (configurable max concurrency)
* OpenAI o3 model handles both grading and prompt engineering
* Context trimming preserves reasoning token validity
* JSONL logs capture all API interactions and results

Configuration:
* Parallelism: Configurable via OptimizerConfig.max_parallel_rollouts (default: 8)
* Context limits: PromptEngineer handles 200k token o3 context automatically
"""

# TODO: consider showing grader text Assistant messages, not just code

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import shutil
import signal
import sys
import tiktoken
import yaml
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional, Union, TypedDict, Literal
from enum import Enum


from claude_code_sdk import (
    ClaudeCodeOptions,
    ClaudeSDKClient,
    SystemMessage,
    UserMessage,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
)
from openai import OpenAI
from openai.types.responses.response import Response
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_function_tool_call_item import (
    ResponseFunctionToolCallItem,
)
from openai.types.responses.response_output_text import ResponseOutputText
from openai.types.responses.response_reasoning_item import ResponseReasoningItem
from pydantic import BaseModel

# Import new modules
from optimizer_config import OptimizerConfig
from docker_manager import DockerManager
from message_formatter import log_message_summary
from logging_utils import DualOutputLogging

# Setup logging using utility class
DualOutputLogging.setup_logging()
logger = DualOutputLogging.get_logger()

# Score evolution tracking
class ScoreEvolutionTracker:
    """Tracks how scores evolve across optimization iterations."""
    
    def __init__(self):
        self.iterations_data = []  # List of iteration score summaries
        
    def add_iteration(self, iteration: int, graded_codes: List[GradedCode]):
        """Add scores from an iteration."""
        # Extract all scores
        overall_scores = [gc.grade.overall_score for gc in graded_codes]
        
        # Extract facet scores
        facet_scores = {}
        if graded_codes:
            # Get all facet names from first result
            facet_names = list(graded_codes[0].grade.axes.keys())
            for facet_name in facet_names:
                facet_scores[facet_name] = [
                    gc.grade.axes[facet_name].score for gc in graded_codes
                ]
        
        # Calculate statistics
        import statistics
        
        def safe_stats(scores):
            if not scores:
                return {"mean": 0, "stdev": 0, "min": 0, "max": 0}
            return {
                "mean": statistics.mean(scores),
                "stdev": statistics.stdev(scores) if len(scores) > 1 else 0,
                "min": min(scores),
                "max": max(scores),
                "count": len(scores)
            }
        
        iteration_summary = {
            "iteration": iteration,
            "overall": safe_stats(overall_scores),
            "facets": {name: safe_stats(scores) for name, scores in facet_scores.items()},
            "timestamp": datetime.now().isoformat()
        }
        
        self.iterations_data.append(iteration_summary)
        
        logger.info(
            "Score evolution tracked",
            iteration=iteration,
            overall_mean=round(iteration_summary["overall"]["mean"], 2),
            overall_stdev=round(iteration_summary["overall"]["stdev"], 2),
            rollout_count=iteration_summary["overall"]["count"]
        )
    
    def generate_report(self, run_dir: Path, log_path: Path) -> str:
        """Generate final score evolution report and plots."""
        if not self.iterations_data:
            return "No score data to report."
        
        report_parts = [
            "=== SCORE EVOLUTION REPORT ===",
            f"Total iterations: {len(self.iterations_data)}",
            f"Log files location: {log_path}",
            "",
            "Overall Score Evolution:"
        ]
        
        # Overall scores table
        for iter_data in self.iterations_data:
            overall = iter_data["overall"]
            report_parts.append(
                f"  Iteration {iter_data['iteration']:2d}: "
                f"{overall['mean']:5.2f} ± {overall['stdev']:4.2f} "
                f"(range: {overall['min']:4.1f}-{overall['max']:4.1f}, n={overall['count']})"
            )
        
        # Facet evolution
        if self.iterations_data[0]["facets"]:
            report_parts.extend(["", "Facet Score Evolution:"])
            facet_names = list(self.iterations_data[0]["facets"].keys())
            
            for facet in facet_names:
                report_parts.append(f"  {facet}:")
                for iter_data in self.iterations_data:
                    facet_stats = iter_data["facets"][facet]
                    report_parts.append(
                        f"    Iter {iter_data['iteration']:2d}: "
                        f"{facet_stats['mean']:5.2f} ± {facet_stats['stdev']:4.2f}"
                    )
        
        # Generate plots
        try:
            plot_path = self._generate_plots(run_dir)
            report_parts.extend(["", f"Score evolution plots saved to: {plot_path}"])
        except Exception as e:
            logger.warning("Failed to generate plots", error=str(e))
            report_parts.extend(["", f"Plot generation failed: {e}"])
        
        report_parts.append("=" * 50)
        return "\n".join(report_parts)
    
    def _generate_plots(self, run_dir: Path) -> Path:
        """Generate score evolution plots using plotnine."""
        import pandas as pd
        from plotnine import (
            ggplot, aes, geom_line, geom_point, geom_errorbar, 
            facet_wrap, theme_minimal, labs, theme, element_text
        )
        import numpy as np
        
        # Prepare data for plotting
        plot_data = []
        
        # Overall scores
        for iter_data in self.iterations_data:
            overall = iter_data["overall"]
            # 69% CI (approximately 1 standard error)
            error = overall["stdev"] / np.sqrt(max(1, overall["count"]))
            plot_data.append({
                "iteration": iter_data["iteration"],
                "facet": "overall",
                "mean": overall["mean"],
                "error": error,
                "ci_lower": overall["mean"] - error,
                "ci_upper": overall["mean"] + error
            })
        
        # Facet scores
        if self.iterations_data[0]["facets"]:
            for facet_name in self.iterations_data[0]["facets"].keys():
                for iter_data in self.iterations_data:
                    facet_stats = iter_data["facets"][facet_name]
                    error = facet_stats["stdev"] / np.sqrt(max(1, facet_stats["count"]))
                    plot_data.append({
                        "iteration": iter_data["iteration"],
                        "facet": facet_name,
                        "mean": facet_stats["mean"],
                        "error": error,
                        "ci_lower": facet_stats["mean"] - error,
                        "ci_upper": facet_stats["mean"] + error
                    })
        
        df = pd.DataFrame(plot_data)
        
        # Create plot
        plot = (
            ggplot(df, aes(x="iteration", y="mean", color="facet")) +
            geom_line(size=1) +
            geom_point(size=2) +
            geom_errorbar(aes(ymin="ci_lower", ymax="ci_upper"), width=0.1) +
            theme_minimal() +
            labs(
                title="Score Evolution Across Iterations",
                x="Iteration",
                y="Score",
                color="Facet",
                caption="Error bars show 69% confidence interval of the mean"
            ) +
            theme(
                plot_title=element_text(size=14, ha="center"),
                legend_position="right"
            )
        )
        
        plot_path = run_dir / "score_evolution.png"
        plot.save(plot_path, width=12, height=8, dpi=300)
        return plot_path

# Global trackers
score_tracker = ScoreEvolutionTracker()

# Global cost tracking
class CostTracker:
    """Tracks total costs across all Claude Code rollouts."""
    
    def __init__(self):
        self.total_cost_usd = 0.0
        self.rollout_count = 0
    
    def add_rollout_cost(self, cost_usd: float):
        """Add cost from a completed rollout."""
        self.total_cost_usd += cost_usd
        self.rollout_count += 1
        logger.info(
            "Rollout cost added",
            rollout_cost_usd=cost_usd,
            total_cost_usd=self.total_cost_usd,
            rollout_count=self.rollout_count,
        )
    
    def report_final_cost(self):
        """Report final cost summary."""
        logger.info(
            "FINAL COST SUMMARY",
            total_cost_usd=self.total_cost_usd,
            rollout_count=self.rollout_count,
            avg_cost_per_rollout_usd=self.total_cost_usd / max(1, self.rollout_count),
        )

# Global cost tracker instance
cost_tracker = CostTracker()

def setup_signal_handlers():
    """Setup signal handlers for graceful cost reporting on interruption."""
    
    def signal_handler(signum, frame):
        logger.info("Interrupt received, reporting costs before exit", signal=signum)
        cost_tracker.report_final_cost()
        sys.exit(1)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

# Load configuration
config = OptimizerConfig()


class ProcessingMode(Enum):
    """Processing mode for prompt optimization."""

    FULL_ROLLOUTS = "full_rollouts"
    SUMMARY = "summary"


class PatternSummarizer:
    """Analyzes rollout patterns and produces insights for prompt engineering."""

    _SYSTEM_MESSAGE = (
        "You are a pattern analysis expert. Your job is to analyze multiple coding task rollouts with their grades and identify key patterns, trends, and insights.\n\n"
        "Given rollout results, you should:\n"
        '1. Identify common failure patterns across tasks (e.g., "broad exception handling appears in 8/10 rollouts")\n'
        '2. Spot recurring code quality issues (e.g., "missing type hints in 70% of solutions")\n'
        '3. Note architectural trends (e.g., "agents consistently choose async approaches for API tasks")\n'
        '4. Highlight grading patterns (e.g., "defensive programming scores consistently low due to exception swallowing")\n'
        '5. Extract actionable insights for prompt improvement (e.g., "current prompt doesn\'t emphasize specific exception handling")\n\n'
        "Output a concise summary focusing on the most impactful patterns that would help a prompt engineer improve the system prompt. Prioritize patterns that appear across multiple tasks and have clear connections to prompt weaknesses."
    )

    async def summarize_patterns(
        self, rollout_results: List[GradedCode], openai_log_path: Path
    ) -> str:
        """Analyze rollout patterns and produce summary for PromptEngineer.

        Args:
            rollout_results: List of GradedCode objects from rollouts
            openai_log_path: Path for logging OpenAI API calls

        Returns:
            Condensed pattern analysis summary
        """
        # Build analysis prompt with rollout data
        rollout_summaries = []
        for i, graded_code in enumerate(rollout_results):
            task_summary = f"Task {i+1}:\n"
            task_summary += f"  Overall Score: {graded_code.grade.overall_score}/10\n"
            task_summary += f"  Key Issues: {graded_code.grade.overall_rationale}\n"

            # Add facet breakdown with scores and rationales
            facet_details = []
            for facet_name, score_with_rationale in graded_code.grade.axes.items():
                facet_details.append(
                    f"\n    {facet_name}: {score_with_rationale.score}/10 - {score_with_rationale.rationale}"
                )
            task_summary += f"  Facets:{''.join(facet_details)}\n"

            # Add file information
            task_summary += (
                f"  Files: {json.dumps(graded_code.code_result.files, indent=2)}\n"
            )

            rollout_summaries.append(task_summary)

        analysis_prompt = (
            f"Analyze these {len(rollout_results)} coding task rollouts and identify key patterns for prompt improvement:\n\n"
            + "\n".join(rollout_summaries)
        )

        # Make OpenAI API call for pattern analysis
        client = OpenAI()
        openai_request = create_openai_request(
            config.openai_model,
            [
                {"role": "system", "content": self._SYSTEM_MESSAGE},
                {"role": "user", "content": analysis_prompt},
            ],
            tools=[],
            tool_choice="auto",
        )

        response = client.responses.create(**openai_request)
        log_openai_request_response(openai_log_path, openai_request, response)

        # Extract pattern summary from response
        for item in response.output:
            if isinstance(item, ResponseOutputMessage) and item.type == "message":
                for content_item in item.content:
                    if isinstance(content_item, ResponseOutputText):
                        pattern_summary = content_item.text
                        
                        # Log the pattern summary with a distinctive tag for easy grepping
                        logger.info(
                            "PATTERN_ANALYSIS_SUMMARY",
                            summary_text=pattern_summary,
                            rollout_count=len(rollout_results),
                            avg_score=sum(r.grade.overall_score for r in rollout_results) / len(rollout_results) if rollout_results else 0
                        )
                        
                        return pattern_summary

        raise RuntimeError("No pattern summary found in response")


class SeedTask(BaseModel):
    id: str
    prompt: str


class Criterion(BaseModel):
    name: str
    description: str
    evaluation_criteria: str


class ScoreWithRationale(BaseModel):
    """Represents a score with its accompanying rationale."""

    score: float
    rationale: str


# Initialize Docker manager at module load time
docker_manager = DockerManager()

# -----------------------------------------------------------------------------
# Helper functions for deduplication and common operations
# -----------------------------------------------------------------------------


def create_openai_request(
    model: str,
    input_data: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    tool_choice: Dict[str, Any],
    reasoning_effort: Optional[str] = None,
) -> Dict[str, Any]:
    """Create standardized OpenAI request dictionary."""
    if reasoning_effort is None:
        reasoning_effort = config.reasoning_effort
    request = {
        "model": model,
        "input": input_data,
        "tools": tools,
        "tool_choice": tool_choice,
    }
    if reasoning_effort:
        request["reasoning"] = {"effort": reasoning_effort}
    return request




# -----------------------------------------------------------------------------
# Helper functions for logging API requests and responses
#
# These functions write JSONL entries for every call to the OpenAI and Anthropic
# APIs.  Each entry includes a timestamp, the request parameters, and the
# response or event data.  They are used throughout the script to aid in
# debugging and auditing of API interactions.


def log_openai_request_response(
    log_path: Path, request: Dict[str, Any], response: Response
) -> None:
    """Append a record of an OpenAI API request and its response to a JSONL file.

    Parameters
    ----------
    log_path : Path
        The path to the JSONL log file.
    request : dict
        A dictionary representing the parameters sent to the OpenAI API.
    response : Response
        The response object returned by the OpenAI library.  We attempt to
        serialise it to JSON; if that fails, we fall back to its string
        representation.
    """
    # Attempt to serialise the response object.  OpenAI responses implement a
    # model_dump() method; if unavailable, fall back to dict(), json(), or str().
    try:
        response_data = (
            response.model_dump()
            if isinstance(response, BaseModel)
            else {"value": str(response)}
        )
    except (AttributeError, TypeError):
        response_data = {"value": str(response)}
    record = {
        "timestamp": datetime.utcnow().isoformat(),
        "request": request,
        "response": response_data,
    }
    with log_path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def log_anthropic_request_event(
    log_path: Path,
    request: Dict[str, Any],
    event: Union[SystemMessage, AssistantMessage, UserMessage, ResultMessage, str],
) -> None:
    """Append a record of an Anthropic request or response event to a JSONL file.

    The caller should first log the request once, then log each event yielded
    by the Claude Code asynchronous generator.  Events are serialised if
    possible; otherwise they are converted to strings.

    Parameters
    ----------
    log_path : Path
        The path to the JSONL log file.
    request : dict
        The request parameters sent to Claude Code, typically containing
        messages and options.
    event : Union[SystemMessage, AssistantMessage, UserMessage, ResultMessage, str]
        An event returned by the Claude Code async generator.  Could be a
        message object or a string.
    """
    try:
        event_data = event if isinstance(event, dict) else str(event)
    except (AttributeError, TypeError):
        event_data = str(event)
    record = {
        "timestamp": datetime.utcnow().isoformat(),
        "request": request,
        "event": event_data,
    }
    with log_path.open("a") as f:
        f.write(json.dumps(record) + "\n")


class CodeResult(BaseModel):
    """Represents the outcome of running Claude Code on a programming task.

    A CodeResult contains only the essential metadata for an agent rollout: the
    task description, the agent identifier, the generated source code files, and a
    timestamp.  It deliberately omits any rationale, since explanations belong
    to the grading step rather than the code generation step.
    """

    task: str
    agent_id: int
    timestamp: str
    messages: List[Dict[str, Any]]  # Serialized Claude SDK messages via asdict()
    files: List[Dict[str, str]]


class Grade(BaseModel):
    """Represents the grading information for a piece of code.

    A Grade stores a mapping from criterion keys to score/rationale pairs,
    as well as an overall score and rationale.  This structure allows for a
    variable number of grading axes defined by the user via the Criterion
    list.  The overall score is provided by the grader and should reflect
    holistic quality, not a simple average of axis scores.
    """

    task: str
    agent_id: int
    axes: Dict[str, ScoreWithRationale]
    overall_score: float
    overall_rationale: str
    timestamp: str


class GradedCode(BaseModel):
    """Combines CodeResult with its Grade for unified handling."""

    code_result: CodeResult
    grade: Grade


async def execute_claude_session(
    task: str,
    options: ClaudeCodeOptions,
    agent_id: int,
    anthropic_log_path: Path,
) -> List[Dict[str, Any]]:
    """Execute Claude Code session and collect messages.
    
    Args:
        task: The task prompt for Claude Code
        options: Claude Code configuration options
        agent_id: Agent identifier for logging
        anthropic_log_path: Path to log Anthropic API calls
        
    Returns:
        List of serialized messages from the session
    """
    message_sequence: List[Dict[str, Any]] = []
    anthropic_request = {
        "prompt": task,
        "options": (
            options.model_dump() if isinstance(options, BaseModel) else str(options)
        ),
    }
    
    log_anthropic_request_event(anthropic_log_path, anthropic_request, "request_sent")
    
    agent_logger = logger.bind(agent_id=agent_id)
    agent_logger.info("Starting Claude Code session")
    
    from claude_code_sdk import ResultMessage
    
    async with ClaudeSDKClient(options=options) as client:
        await client.query(task)
        async for message in client.receive_messages():
            log_anthropic_request_event(anthropic_log_path, anthropic_request, message)
            message_sequence.append(asdict(message))
            log_message_summary(message, logger, agent_id)
            
            if isinstance(message, ResultMessage):
                agent_logger.info(
                    "Session completed",
                    duration_ms=message.duration_ms,
                    cost_usd=message.total_cost_usd,
                    is_error=message.is_error,
                )
                # Track rollout cost
                cost_tracker.add_rollout_cost(message.total_cost_usd)
                break
                
    return message_sequence


def gather_agent_files(work_dir: Path) -> List[Dict[str, str]]:
    """Gather all relevant files from agent working directory.
    
    Args:
        work_dir: The agent's working directory
        
    Returns:
        List of dicts with 'path' and 'content' keys for each file
    """
    files_info: List[Dict[str, str]] = []
    
    for file_path in work_dir.rglob("*"):
        if not file_path.is_file():
            continue

        if file_path.name in config.exclude_files:
            continue

        if any(file_path.suffix == ext for ext in config.exclude_extensions):
            continue

        if any(excluded_dir in file_path.parts for excluded_dir in config.exclude_dirs):
            continue

        if file_path.name.startswith(".") and not file_path.name in {
            ".env",
            ".env.example",
        }:
            continue

        relative = file_path.relative_to(work_dir).as_posix()
        try:
            content = file_path.read_text()
        except UnicodeDecodeError as e:
            logger.warning(
                "Failed to decode file as UTF-8",
                file_path=str(file_path),
                relative_path=relative,
                error=str(e),
                file_size=file_path.stat().st_size
            )
            content = "<<not a plaintext file>>"
        files_info.append({"path": relative, "content": content})
        
    return files_info


async def run_claude_code(
    task: str,
    system_prompt: str,
    agent_id: int,
    task_id: str,
    base_dir: Path,
    anthropic_log_path: Path,
) -> CodeResult:
    """Run a single Claude Code agent on the given task.

    This function sets up an isolated working directory for the agent,
    writes the system prompt to a uniquely numbered ``CLAUDE-XXXX.md``
    file (where XXXX is the prompt version), and then queries the
    Claude Code model to generate code that solves the task.  The returned
    CodeResult contains the generated code and any rationale provided
    by the model.

    Parameters
    ----------
    task : str
        The user-facing task description for which code should be generated.
    system_prompt : str
        The system prompt guiding the agent's behaviour.
    agent_id : int
        An identifier distinguishing this agent instance within a batch.
    base_dir : Path
        The path where the agent's working directory should be created.

    Returns
    -------
    CodeResult
        A dataclass containing the task, agent identifier, generated code,
        rationale, and timestamp.
    """
    # Create a unique working directory for this agent
    # Use an absolute path for the working directory to ensure the SDK runs in
    # the intended location regardless of the current working directory.  The
    # resolved path also prevents relative path traversal issues.
    # Include task_id and agent_id to avoid conflicts when multiple agents work on different tasks
    work_dir = (base_dir / f"task_{task_id}" / f"agent_{agent_id}").resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    # Log the working directory for this agent so that users
    # know where the agent's files are being saved.  This occurs at the start
    # of each agent run.
    agent_logger = logger.bind(agent_id=agent_id, task_id=task_id)
    agent_logger.info("Agent starting", work_dir=str(work_dir), task_preview=task[:100])

    # Write the system prompt into CLAUDE.md inside the agent's working directory.
    # The actual prompt version files are stored at the run directory level.
    (work_dir / "CLAUDE.md").write_text(system_prompt)

    os.environ["BASH_MAX_TIMEOUT_MS"] = str(config.bash_timeout_ms)

    options = ClaudeCodeOptions(
        allowed_tools=None,  # Full tool access for autonomous execution
        cwd=work_dir,
        max_turns=config.max_turns,
        permission_mode="bypassPermissions",  # Required for Docker container execution
        mcp_servers={},
    )
    
    # Execute Claude Code session and collect messages
    message_sequence = await execute_claude_session(
        task, options, agent_id, anthropic_log_path
    )

    # Gather all files created by the agent
    files_info = gather_agent_files(work_dir)

    timestamp = datetime.utcnow().isoformat()
    return CodeResult(
        task=task,
        agent_id=agent_id,
        timestamp=timestamp,
        messages=message_sequence,
        files=files_info,
    )


async def grade_code(
    result: CodeResult, criteria: List[Criterion], openai_log_path: Path
) -> Grade:
    """Grade a piece of code using the OpenAI Responses API with function calling.

    The grader evaluates the code on a set of facets (criteria) defined by the
    caller.  Each facet must have a unique key, a description, and an
    evaluation criteria explaining how to assess it.  The grader uses a
    function call (`submit_grades`) to return scores and rationales for each
    facet plus an overall score and rationale.  The overall score is left to
    the model's discretion; it is not computed as the average of the facet
    scores.

    Parameters
    ----------
    result : CodeResult
        The code result to be graded.
    criteria : List[Criterion]
        Facets to evaluate.  Each facet will appear as a
        property in the function schema.
    openai_log_path : Path
        Path to JSONL file where requests and responses to the OpenAI API
        will be logged.
    """
    client = OpenAI()

    # Dynamically build the function schema for the grader based on the
    # provided criteria.  Each facet becomes a property in the function
    # parameters with its own score and rationale fields.  We also include
    # an 'overall' property for the overall assessment.
    properties: Dict[str, Any] = {}
    required_keys: List[str] = []
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
    # Add overall property
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
        "name": "submit_grades",
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

    # Build the input messages.  We give the model the task description and
    # concatenated code, and instruct it to evaluate according to the facets.
    input_messages: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are an expert Python instructor and code reviewer. For the given task and code, "
                "evaluate the submission according to the provided facets and then call the submit_grades "
                "function with your scores and rationales."
            ),
        },
        {
            "role": "user",
            "content": f"Task: {result.task}\n\nFiles:\n{json.dumps(result.files, indent=2)}",
        },
    ]

    # Prepare request for logging
    openai_request = {
        "model": "o3",
        "input": input_messages,
        "tools": [grading_tool],
        "tool_choice": {"type": "function", "name": "submit_grades"},
    }

    # Call the model.  We enforce the tool choice so the model must call
    # submit_grades and return the grading JSON according to the schema.
    grade_logger = logger.bind(
        agent_id=result.agent_id, task_id=getattr(result, "task_id", "unknown")
    )
    grade_logger.info("Making OpenAI grading call")

    openai_request = create_openai_request(
        config.openai_model,
        input_messages,
        [grading_tool],
        {"type": "function", "name": "submit_grades"},
    )
    response = client.responses.create(**openai_request)
    # Log request and response
    log_openai_request_response(openai_log_path, openai_request, response)
    grade_logger.info("OpenAI grading completed")

    # Extract the function_call item from the response first
    call: Optional[Union[ResponseFunctionToolCall, ResponseFunctionToolCallItem]] = None
    for item in response.output or []:
        if (
            isinstance(item, ResponseFunctionToolCallItem)
            and item.type == "function_call"
        ):
            call = item
            break
        elif isinstance(item, ResponseFunctionToolCall):
            call = item
            break

    if call is None:
        # Log the response output for debugging
        output_types = []
        for item in response.output or []:
            output_types.append(
                {
                    "type": str(type(item)),
                    "has_type_attr": hasattr(item, "type"),
                    "type_value": (
                        getattr(item, "type", None) if hasattr(item, "type") else None
                    ),
                }
            )

        grade_logger.error(
            "No function_call found in grading response",
            response_output=output_types,
            tool_choice=openai_request.get("tool_choice"),
        )

        # Check if we got a message instead
        for item in response.output or []:
            if isinstance(item, ResponseOutputMessage) and item.type == "message":
                for content_item in item.content:
                    if isinstance(content_item, ResponseOutputText):
                        grade_logger.error(
                            "Got text response instead of function call",
                            text=content_item.text[:200],
                        )

        raise RuntimeError(
            "No function_call found in grading response - check logs for details"
        )

    # Extract and log grading results before processing
    args_str = call.arguments
    if isinstance(args_str, str):
        grades_data = json.loads(args_str)
        facet_results = {}
        for facet_name, facet_data in grades_data.items():
            if isinstance(facet_data, dict) and "score" in facet_data:
                score = facet_data.get("score", 0)
                rationale = facet_data.get("rationale", "")
                facet_results[facet_name] = {"score": score, "rationale": rationale}

        grade_logger.info("Grading results", facets=facet_results)

        # Also log readable results for each facet
        for facet_name, facet_data in facet_results.items():
            score = facet_data["score"]
            rationale = (
                facet_data["rationale"][:config.truncation_length] + "..."
                if len(facet_data["rationale"]) > config.truncation_length
                else facet_data["rationale"]
            )
            grade_logger.info(
                "Facet graded",
                facet=facet_name,
                score=score,
                rationale=rationale,
            )

    # Determine the function name
    if call.name != "submit_grades":
        raise RuntimeError(f"Unexpected function name: {call.name}")

    # Extract the arguments string
    if not isinstance(call.arguments, str):
        raise ValueError(
            f"Could not retrieve arguments from submit_grades call: {call}"
        )
    # Parse the JSON string into a dict
    result_data = json.loads(call.arguments)

    # Map scores and rationales back into the Grade object
    axes: Dict[str, ScoreWithRationale] = {}
    for crit in criteria:
        section = result_data.get(crit.name)
        if not section:
            raise ValueError(
                f"Grading output missing facet '{crit.name}': {result_data}"
            )
        axes[crit.name] = ScoreWithRationale(
            score=float(section.get("score", 0)),
            rationale=str(section.get("rationale", "")),
        )
    overall_section = result_data.get("overall")
    if not overall_section:
        raise ValueError(f"Grading output missing 'overall' section: {result_data}")
    overall_score = float(overall_section.get("score", 0))
    overall_rationale = str(overall_section.get("rationale", ""))
    timestamp = datetime.utcnow().isoformat()
    return Grade(
        task=result.task,
        agent_id=result.agent_id,
        axes=axes,
        overall_score=overall_score,
        overall_rationale=overall_rationale,
        timestamp=timestamp,
    )


@dataclass
class Turn:
    """A complete conversational turn in the PromptEngineer."""

    reasoning: List[
        Union[ResponseOutputMessage, ResponseReasoningItem]
    ]  # OpenAI reasoning from propose()
    function_call_message: Union[
        ResponseFunctionToolCall, ResponseFunctionToolCallItem
    ]  # The original function call message from OpenAI
    proposed_prompt: str  # The prompt that was proposed (extracted from function call)
    grades: str  # Grading results from testing the prompt

    @property
    def messages(self) -> List[Dict[str, Any]]:
        """Convert turn into OpenAI API message sequence."""
        msgs = []

        # Add all reasoning items (filtered to remove response-only fields)
        for reasoning_item in self.reasoning:
            msg_dict = reasoning_item.model_dump()
            if "status" in msg_dict:
                del msg_dict["status"]
            msgs.append(msg_dict)

        # Add the original function call message (preserving OpenAI's original object/IDs)
        function_call_dict = self.function_call_message.model_dump()
        if "status" in function_call_dict:
            del function_call_dict["status"]
        msgs.append(function_call_dict)

        # Add function call output with grading results
        msgs.append({
            "type": "function_call_output",
            "call_id": self.function_call_message.call_id,
            "output": self.grades,
        })

        return msgs


class PromptEngineer:
    """Manages conversation state and token counting for prompt optimization."""

    def __init__(
        self, processing_mode: ProcessingMode = ProcessingMode.FULL_ROLLOUTS
    ) -> None:
        """Initialize empty conversation state with mode-specific system message."""
        self._turns: List[Turn] = []
        self._processing_mode = processing_mode
        self._system_message = self._build_system_message(processing_mode)

    def _build_system_message(self, mode: ProcessingMode) -> Dict[str, str]:
        """Build system message based on processing mode."""
        base_content = "You are a prompt engineer. Your job is to "

        if mode == ProcessingMode.FULL_ROLLOUTS:
            analysis_part = "analyze rollouts from coding tasks"
        else:  # ProcessingMode.SUMMARY
            analysis_part = (
                "analyze pattern summaries and insights from coding task rollouts"
            )

        shared_end = " and iteratively improve the system prompt to get better results. The coding assistant should write working code to files, not just show code in conversation. Focus on prompts that encourage creating actual file artifacts. "
        shared_end += (
            "The coding assistant works through tools providing it I/O access to a filesystem and to shell "
            "command execution. The assistant should write working code to files, not just show code in conversation. "
            "It already comes equipped with a system prompt that teaches it how to use its tools correctly to write code. "
            "Do not try to tell it how to do the low-level mechanics of code editing/execution - it already has the correct instructions "
            "on what tools to use, how to use them, etc. in a fixed prompt and your instructions would likely just "
            "conflict and make it worse."
        )
        return {"role": "system", "content": base_content + analysis_part + shared_end}

    @property
    def prompt_messages(
        self,
    ) -> List[
        Union[
            Dict[str, Any],
            ResponseOutputMessage,
            ResponseReasoningItem,
            ResponseFunctionToolCall,
            ResponseFunctionToolCallItem,
        ]
    ]:
        """Get conversation messages with system message prepended."""
        messages: List[
            Union[
                Dict[str, Any],
                ResponseOutputMessage,
                ResponseReasoningItem,
                ResponseFunctionToolCall,
                ResponseFunctionToolCallItem,
            ]
        ] = [self._system_message]

        # Flatten all turns using their message getter
        for turn in self._turns:
            messages.extend(turn.messages)

        return messages

    def _count_tokens(self, model: str = "gpt-4o") -> int:
        """Private: Count tokens in current conversation."""
        enc = tiktoken.encoding_for_model(model)
        tokens = 0

        # Use the same logic as before - just count all messages in prompt_messages
        for m in self.prompt_messages:
            if hasattr(m, "model_dump"):
                # OpenAI SDK object - serialize it
                m_str = str(m.model_dump())
                tokens += len(enc.encode(m_str))
            elif isinstance(m, dict):
                # Dict message - serialize relevant fields
                if "content" in m:
                    tokens += len(enc.encode(str(m["content"])))
                if "arguments" in m:
                    tokens += len(enc.encode(str(m["arguments"])))
                if "output" in m:
                    tokens += len(enc.encode(str(m["output"])))
            else:
                # Fallback - serialize the whole thing
                tokens += len(enc.encode(str(m)))

        return tokens

    def _trim_context_if_needed(self, max_tokens: Optional[int] = None) -> None:
        """Private: Trim conversation if it exceeds token limit."""
        if max_tokens is None:
            max_tokens = config.max_context_tokens
        if self._count_tokens() > max_tokens and len(self._turns) > 2:
            # Keep only last 2 complete turns - each turn is atomic and complete
            self._turns = self._turns[-2:]
            logger.info(
                "Trimmed context",
                remaining_turns=len(self._turns),
                estimated_tokens=self._count_tokens(),
            )

    def _build_rollout_summaries(self, rollouts: List[GradedCode]) -> List[str]:
        """Build summaries of rollout results for conversation."""
        summaries = []
        for graded_code in rollouts:
            # Keep messages as SDK objects, serialize them simply as JSON for the LLM
            message_lines = [
                json.dumps(evt) for evt in graded_code.code_result.messages
            ]
            files_json = json.dumps(graded_code.code_result.files, indent=2)
            axis_parts = []
            for axis_name, score_with_rationale in graded_code.grade.axes.items():
                axis_parts.append(
                    f"  {axis_name}: {score_with_rationale.score}/10 - {score_with_rationale.rationale}"
                )

            summary = f"""Task: {graded_code.code_result.task}
Overall Grade: {graded_code.grade.overall_score}
Axes:
{chr(10).join(axis_parts)}
Files:
{files_json}
Full Messages:
{chr(10).join(message_lines)}"""
            summaries.append(summary)
        return summaries

    def build_grades_message(self, rollouts: List[GradedCode]) -> str:
        """Build grades message from rollout results."""
        rollout_summaries = self._build_rollout_summaries(rollouts)
        return f"Here are the results from testing the current system prompt on {len(rollouts)} coding tasks. Analyze these results and propose an improved system prompt.\n\n{chr(10).join(['---'] * 2).join(rollout_summaries)}"

    async def propose_prompt(self, openai_log_path: Path) -> Tuple[
        List[Union[ResponseOutputMessage, ResponseReasoningItem]],
        Union[ResponseFunctionToolCall, ResponseFunctionToolCallItem],
        str,
    ]:
        """Make OpenAI API call to get next prompt proposal.

        Returns:
            (reasoning_messages, function_call_message, proposed_prompt)
        """
        # Trim context if needed before API call
        self._trim_context_if_needed()

        # Create OpenAI Responses API tools schema
        tools = [
            {
                "type": "function",
                "name": "submit_prompt",
                "description": "Submit an improved system prompt",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "The improved system prompt",
                        }
                    },
                    "required": ["prompt"],
                },
            }
        ]

        # Call OpenAI Responses API with current conversation
        client = OpenAI()
        openai_request = create_openai_request(
            config.openai_model,
            self.prompt_messages,
            tools,
            {"type": "function", "name": "submit_prompt"},
        )
        response: Response = client.responses.create(**openai_request)
        log_openai_request_response(openai_log_path, openai_request, response)

        # Separate reasoning messages from function call
        reasoning_messages: List[
            Union[ResponseOutputMessage, ResponseReasoningItem]
        ] = []
        function_call_item: Optional[
            Union[ResponseFunctionToolCall, ResponseFunctionToolCallItem]
        ] = None

        for item in response.output:
            if isinstance(
                item, (ResponseFunctionToolCall, ResponseFunctionToolCallItem)
            ):
                function_call_item = item
            elif isinstance(item, (ResponseOutputMessage, ResponseReasoningItem)):
                reasoning_messages.append(item)

        if function_call_item is None:
            raise RuntimeError("No function_call found in response")

        # Extract function call details with proper type checking
        call_name = function_call_item.name
        arguments_str = function_call_item.arguments

        if call_name != "submit_prompt":
            raise RuntimeError(f"Unexpected function name: {call_name}")

        if not isinstance(arguments_str, str):
            raise ValueError(f"Invalid arguments format: {arguments_str}")

        try:
            args_dict = json.loads(arguments_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Could not parse arguments: {arguments_str}") from e

        claude_prompt = args_dict.get("prompt", "").strip()
        if not claude_prompt:
            raise ValueError("Empty prompt returned")

        logger.info(
            "Generated new prompt",
            prompt_length=len(claude_prompt),
            conversation_turns=len(self._turns),
        )

        return reasoning_messages, function_call_item, claude_prompt

    def add_result(
        self,
        reasoning: List[Union[ResponseOutputMessage, ResponseReasoningItem]],
        function_call_message: Union[
            ResponseFunctionToolCall, ResponseFunctionToolCallItem
        ],
        proposed_prompt: str,
        grades: str,
    ) -> None:
        """Add completed turn to conversation history.

        Args:
            reasoning: OpenAI's reasoning messages from propose_prompt()
            function_call_message: The original function call message from OpenAI
            proposed_prompt: The prompt that was proposed and tested
            grades: Grading results from testing this prompt
        """
        turn = Turn(
            reasoning=reasoning,
            function_call_message=function_call_message,
            proposed_prompt=proposed_prompt,
            grades=grades,
        )
        self._turns.append(turn)

        logger.info(
            "Added turn to conversation",
            conversation_turns=len(self._turns),
            grades_length=len(grades),
        )


async def optimize_prompts(
    seed_tasks: List[SeedTask],
    iterations: int = 3,
    rollouts_per_task: int = 2,
    base_output_dir: str = "./agent_output",
    max_parallel_rollouts: Optional[int] = None,
    tasks_per_iteration: Optional[int] = None,
    processing_mode: ProcessingMode = ProcessingMode.FULL_ROLLOUTS,
) -> Path:
    """Run the prompt optimisation loop.

    This is the main entry point for running multiple iterations of the algorithm. It
    repeatedly executes batches of Claude Code agents on the seed tasks in parallel,
    grades the generated solutions using OpenAI's Responses API, updates the system
    prompt using a prompt engineer (OpenAI o3), and logs results to JSONL files.

    Parameters
    ----------
    seed_tasks : List[SeedTask]
        The programming tasks to use as the benchmark for optimisation.
    iterations : int, optional
        The number of optimisation iterations to perform (default 3).
    rollouts_per_task : int, optional
        The number of Claude Code agents to sample per task in each iteration (default 2).
    base_output_dir : str, optional
        Base directory where agent working directories and logs will be stored.
    max_parallel_rollouts : int, optional
        Maximum number of concurrent Claude Code rollouts (default from config).
    tasks_per_iteration : int, optional
        Number of tasks to randomly sample (with replacement) per iteration. 
        If None, uses all seed tasks (default None).
    """
    if max_parallel_rollouts is None:
        max_parallel_rollouts = config.max_parallel_rollouts
    # Create a unique prefix for this run to avoid collisions with previous
    # executions.  The prefix is based on the current UTC timestamp.  All
    # working directories and logs for this run will be stored under
    # base_output_dir / run_prefix.
    run_prefix = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    base_dir = (Path(base_output_dir) / run_prefix).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Run directory created", run_directory=str(base_dir), run_prefix=run_prefix
    )

    # Set up Docker wrapper for isolated Claude Code execution
    external_wrapper = Path(__file__).parent / "docker_claude_wrapper.sh"
    wrapper_script = docker_manager.setup_wrapper(base_dir, external_wrapper)
    logger.info("Docker wrapper configured", wrapper_script=str(wrapper_script))
    
    try:
        # Prepare JSONL log files
        inner_log_path = base_dir / "inner_agent_log.jsonl"
        grader_log_path = base_dir / "grader_log.jsonl"
        prompt_log_path = base_dir / "prompt_engineer_log.jsonl"
        # Prepare API log files for both OpenAI and Anthropic
        openai_api_log_path = base_dir / "openai_api_log.jsonl"
        anthropic_api_log_path = base_dir / "anthropic_api_log.jsonl"

        # Load grading criteria from YAML configuration file.
        graders_path = Path("graders_consolidated.yaml")
        if not graders_path.exists():
            raise FileNotFoundError(
                "graders_consolidated.yaml file is required but was not found."
            )

        with graders_path.open("r") as f:
            graders_data = yaml.safe_load(f)
        grader_entries = graders_data.get("graders", [])
        if not isinstance(grader_entries, list) or not grader_entries:
            raise ValueError(
                "graders.yaml must contain a 'graders' list with at least one entry."
            )
        criteria: List[Criterion] = []
        for entry in grader_entries:
            try:
                crit = Criterion(**entry)
                criteria.append(crit)
            except (TypeError, ValueError, KeyError) as e:
                raise ValueError(f"Invalid grader entry {entry}: {e}") from e

        # Initialize the prompt engineer for the entire optimization process.
        engineer = PromptEngineer(processing_mode)

        # Generate initial prompt without any rollout data
        prev_reasoning, prev_function_call, current_prompt = await engineer.propose_prompt(
            openai_api_log_path
        )

        # Create semaphore for controlling parallel rollouts
        rollout_semaphore = asyncio.Semaphore(max_parallel_rollouts)

        # Define the inner rollout function
        async def run_single_rollout(
            task: SeedTask, rollout_id: int, iteration: int
        ) -> GradedCode:
            """Run a single rollout with semaphore control."""
            async with rollout_semaphore:
                # Run Claude Code agent
                code_result = await run_claude_code(
                    task.prompt,
                    current_prompt,
                    agent_id=rollout_id,
                    task_id=task.id,
                    base_dir=base_dir / f"iter_{iteration}",
                    anthropic_log_path=anthropic_api_log_path,
                )

                # Grade the result
                grade = await grade_code(code_result, criteria, openai_api_log_path)

                logger.info(
                    "Rollout completed",
                    task_id=task.id,
                    rollout_id=rollout_id,
                    iteration=iteration,
                    overall_score=grade.overall_score,
                )

                return GradedCode(code_result=code_result, grade=grade)

        # Log experiment configuration
        tasks_per_iter = tasks_per_iteration if tasks_per_iteration is not None else len(seed_tasks)
        logger.info(
            "Prompt optimization experiment starting",
            task_count=len(seed_tasks),
            task_ids=[task.id for task in seed_tasks],
            rollouts_per_task=rollouts_per_task,
            total_iterations=iterations,
            tasks_per_iteration=tasks_per_iter,
            total_agents=tasks_per_iter * rollouts_per_task * iterations,
            grading_criteria_count=len(criteria),
            initial_prompt=current_prompt,
        )

        for iteration in range(1, iterations + 1):
            iter_logger = logger.bind(iteration=iteration, total_iterations=iterations)
            iter_logger.info("Iteration starting")

            # Write the current prompt to this iteration's directory
            iter_dir = base_dir / f"iter_{iteration}"
            iter_dir.mkdir(parents=True, exist_ok=True)
            (iter_dir / "CLAUDE.md").write_text(current_prompt)

            # Select tasks for this iteration
            if tasks_per_iteration is not None:
                # Randomly sample tasks with replacement
                iteration_tasks = random.choices(seed_tasks, k=tasks_per_iteration)
                iter_logger.info(
                    "Sampled tasks for iteration",
                    sampled_count=tasks_per_iteration,
                    unique_tasks=len(set(task.id for task in iteration_tasks)),
                    task_ids=[task.id for task in iteration_tasks],
                )
            else:
                # Use all seed tasks
                iteration_tasks = seed_tasks

            # Create all rollout tasks for fully parallel execution
            # Each rollout runs: Claude Code agent → grading → logging
            # Semaphore controls max concurrent rollouts to prevent resource exhaustion
            all_rollouts = []
            for task in iteration_tasks:
                for rollout_id in range(rollouts_per_task):
                    all_rollouts.append(run_single_rollout(task, rollout_id, iteration))

            iter_logger.info(
                "Starting parallel rollouts",
                total_rollouts=len(all_rollouts),
                max_parallel=max_parallel_rollouts,
            )

            # Execute all rollouts in parallel with semaphore-based concurrency control
            iteration_results = await asyncio.gather(*all_rollouts)

            iter_logger.info(
                "All rollouts completed", completed_rollouts=len(iteration_results)
            )

            # Log results to JSONL files
            with inner_log_path.open("a") as f:
                for graded_code in iteration_results:
                    record = {
                    "iteration": iteration,
                    **graded_code.code_result.model_dump(),
                    }
                    f.write(json.dumps(record) + "\n")

            with grader_log_path.open("a") as f:
                for graded_code in iteration_results:
                    record = {"iteration": iteration, **graded_code.grade.model_dump()}
                    f.write(json.dumps(record) + "\n")

            # Display simple metrics to CLI
            overall_scores = [
                graded_code.grade.overall_score for graded_code in iteration_results
            ]
            avg_overall = (
                sum(overall_scores) / len(overall_scores) if overall_scores else 0.0
            )
            iter_logger.info(
                "Iteration complete", average_overall_score=round(avg_overall, 2)
            )
            
            # Track score evolution for this iteration
            score_tracker.add_iteration(iteration, iteration_results)
            
            # Generate and save score evolution report and plots after each iteration
            evolution_report = score_tracker.generate_report(base_dir, base_dir / "logs")
            report_path = base_dir / f"score_evolution_iter_{iteration}.txt"
            report_path.write_text(evolution_report)
            iter_logger.info(
                "Score evolution report generated", 
                report_path=str(report_path),
                iteration=iteration
            )

            # Add completed turn to PE conversation (current prompt + grades or pattern summary)
            if processing_mode == ProcessingMode.FULL_ROLLOUTS:
                grades = engineer.build_grades_message(iteration_results)
                iter_logger.info(
                    "ITERATION_FEEDBACK_MODE",
                    mode="full_rollouts",
                    grades_length=len(grades)
                )
            else:  # ProcessingMode.SUMMARY
                summarizer = PatternSummarizer()
                grades = await summarizer.summarize_patterns(
                    iteration_results, openai_api_log_path
                )
                iter_logger.info(
                    "ITERATION_FEEDBACK_MODE",
                    mode="pattern_summary",
                    summary_length=len(grades)
                )

            engineer.add_result(prev_reasoning, prev_function_call, current_prompt, grades)

            # Generate next prompt using PE
            prev_reasoning, prev_function_call, new_prompt = await engineer.propose_prompt(
                openai_api_log_path
            )

            # Log the new prompt in JSONL
            with prompt_log_path.open("a") as f:
                prompt_record = {
                    "iteration": iteration,
                    "timestamp": datetime.utcnow().isoformat(),
                    "system_prompt": new_prompt,
                }
                f.write(json.dumps(prompt_record) + "\n")

            current_prompt = new_prompt

        logger.info("Optimization complete", logs_directory=str(base_dir))
        return base_dir
    finally:
        # Always cleanup Docker wrapper
        docker_manager.cleanup()


def main() -> None:
    """Entry point for standalone execution."""
    parser = argparse.ArgumentParser(
        description="Parallel prompt optimization system for Claude Code agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --iterations 5 --rollouts-per-task 3
  %(prog)s --mode summary --iterations 1 --rollouts-per-task 1
        """,
    )

    parser.add_argument(
        "--iterations",
        type=int,
        default=10,
        help="Number of optimization iterations (default: %(default)s)",
    )

    parser.add_argument(
        "--rollouts-per-task",
        type=int,
        default=1,
        help="Number of agent rollouts per seed task (default: %(default)s)",
    )

    parser.add_argument(
        "--mode",
        type=str,
        choices=[mode.value for mode in ProcessingMode],
        default=ProcessingMode.FULL_ROLLOUTS.value,
        help="Processing mode: full_rollouts runs complete agent sessions, summary uses condensed feedback (default: %(default)s)",
    )

    parser.add_argument(
        "--max-parallel",
        type=int,
        default=4,
        help="Maximum parallel rollouts (default: %(default)s)",
    )

    parser.add_argument(
        "--tasks-per-iteration",
        type=int,
        default=None,
        help="Number of tasks to randomly sample (with replacement) per iteration. If not specified, uses all seed tasks",
    )

    args = parser.parse_args()

    # Setup signal handlers for graceful cost reporting on interruption
    setup_signal_handlers()

    # Convert string mode back to enum
    processing_mode = ProcessingMode(args.mode)

    # Load seed tasks from a YAML file.  The file 'seeds.yaml' should contain a
    # top-level list of objects with keys 'id' and 'prompt'.  The 'prompt'
    # field is used as the programming task.  Descriptions are ignored.
    seeds_path = Path("seeds.yaml")
    if not seeds_path.exists():
        raise FileNotFoundError("seeds.yaml file is required but was not found.")

    with seeds_path.open("r") as f:
        seeds_data = yaml.safe_load(f)
    if not isinstance(seeds_data, list) or not seeds_data:
        raise ValueError("seeds.yaml must contain a list of seed task objects.")
    seed_tasks = []
    for entry in seeds_data:
        seed_tasks.append(SeedTask(**entry))

    # Run the optimisation loop.  Adjust iterations and rollouts per task as desired.
    # The PromptEngineer will generate the initial prompt automatically.
    run_dir = asyncio.run(
        optimize_prompts(
            seed_tasks,
            iterations=args.iterations,
            rollouts_per_task=args.rollouts_per_task,
            base_output_dir="./agent_output",
            max_parallel_rollouts=args.max_parallel,
            tasks_per_iteration=args.tasks_per_iteration,
            processing_mode=processing_mode,
        )
    )
    
    # Generate final score evolution report
    final_evolution_report = score_tracker.generate_report(run_dir, run_dir)
    final_report_path = run_dir / "final_score_evolution_report.txt"
    final_report_path.write_text(final_evolution_report)
    
    print("\n" + "="*60)
    print(final_evolution_report)
    print("="*60)
    
    logger.info(
        "Final score evolution report generated",
        report_path=str(final_report_path),
        run_directory=str(run_dir)
    )
    
    # Report final cost summary
    cost_tracker.report_final_cost()


if __name__ == "__main__":
    main()

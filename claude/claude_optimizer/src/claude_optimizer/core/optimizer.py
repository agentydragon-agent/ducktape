"""Parallel prompt optimization system for coding agents.

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
* Docker containerization for isolated coding agent execution
* OpenAI Responses API integration for grading and prompt engineering
* PromptEngineer class with persistent conversation state and context trimming
* Structured logging with JSON output for comprehensive tracking

Architecture:
* Coding agents run in isolated Docker containers for safety
* Rollouts execute in parallel (configurable max concurrency)
* OpenAI o3 model handles both grading and prompt engineering
* Context trimming preserves reasoning token validity
* JSONL logs capture all API interactions and results

Configuration:
* Parallelism: Configurable via OptimizerConfig.max_parallel_rollouts (default: 8)
* Context limits: PromptEngineer handles 200k token o3 context automatically
"""

# TODO: consider showing grader text Assistant messages, not just code
# TODO: track exact OpenAI & Anthropic model used in database tables

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import json
import random
import signal
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from claude_code_sdk import ResultMessage
from openai import OpenAI

from claude_optimizer.config import OptimizerConfig
from claude_optimizer.core.containerized_claude import TaskClaude
from claude_optimizer.core.exceptions import ContextWindowExceededException
from claude_optimizer.core.file_ops import should_exclude_file
from claude_optimizer.core.grader import grade_code
from claude_optimizer.core.jsonl_logger import JSONLLogger, safe_serialize
from claude_optimizer.core.logging_openai_client import (
    LoggingOpenAIClient,
    LoggingOpenAIModel,
)
from claude_optimizer.core.logging_utils import DualOutputLogging
from claude_optimizer.core.models import (
    CodeResult,
    Criterion,
    FileInfo,
    GradedCode,
    SeedTask,
)
from claude_optimizer.core.prompt_engineer import (
    FeedbackMode,
    FullRolloutsFeedbackProvider,
    PromptEngineer,
    StatsOnlyFeedbackProvider,
)
from claude_optimizer.core.summarizer import PatternSummarizer
from claude_optimizer.core.truncation_utils import TruncationManager
from claude_optimizer.core.yaml_loader import load_yaml_files

# Database removed - using JSON files instead
from claude_optimizer.plots import ScoreEvolutionTracker

# Setup logging using utility class
DualOutputLogging.setup_logging()
logger = DualOutputLogging.get_logger()

# Global trackers
score_tracker = ScoreEvolutionTracker()


# Global cost tracking
@dataclass
class CostTracker:
    """Tracks total costs across all coding agent rollouts."""

    total_cost_usd = 0.0
    rollout_count = 0

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


# -----------------------------------------------------------------------------
# Helper functions for deduplication and common operations
# -----------------------------------------------------------------------------


def gather_agent_files(
    work_dir: Path,
    cfg: OptimizerConfig,
    trunc_mgr: TruncationManager | None = None,
) -> list[dict[str, str]]:
    """Gather all relevant files from agent working directory.

    Args:
        work_dir: The agent's working directory

    Returns:
        List of dicts with 'path' and 'content' keys for each file
    """
    files_info: list[dict[str, str]] = []
    t_mgr = trunc_mgr or TruncationManager(cfg)

    for file_path in work_dir.rglob("*"):
        if not file_path.is_file():
            continue

        relative_path = file_path.relative_to(work_dir).as_posix()
        if any(
            fnmatch.fnmatch(relative_path, pattern)
            or fnmatch.fnmatch(file_path.name, pattern)
            for pattern in cfg.exclude_patterns
        ):
            continue

        relative = file_path.relative_to(work_dir).as_posix()
        content = t_mgr.truncate_file_by_bytes(
            file_path,
            cfg.truncation.max_file_size_grading,
        )

        files_info.append({"path": relative, "content": content})

    return t_mgr.truncate_files_by_tokens(
        files_info,
        cfg.tokens.max_files_tokens,
    )


def should_exclude_file(
    relative_path: str,
    filename: str,
    cfg: OptimizerConfig,
) -> bool:
    """Check if a file should be excluded based on configuration patterns.

    Args:
        relative_path: File path relative to working directory
        filename: Just the filename part
    """
    return any(
        fnmatch.fnmatch(relative_path, pattern) or fnmatch.fnmatch(filename, pattern)
        for pattern in cfg.exclude_patterns
    )


async def run_claude_code(
    seed_task: SeedTask,
    system_prompt: str,
    agent_id: int,
    output_dir: Path,
    anthropic_log: JSONLLogger,
    cfg: OptimizerConfig,
) -> CodeResult:
    """Run a single coding agent on the given task using containerized Claude.

    This function uses the TaskClaude proxy to run Claude inside a Docker container
    with proper PATH isolation. The system prompt is written inside the container,
    and files are automatically copied to the host for grader access.

    Parameters
    ----------
    seed_task : SeedTask
        The task object containing prompt and configuration.
    system_prompt : str
        The system prompt guiding the agent's behaviour.
    agent_id : int
        An identifier distinguishing this agent instance within a batch.
    output_dir : Path
        Directory where agent output files will be saved.
    anthropic_log : JSONLLogger
        Logger for Anthropic API calls.
    rollout_id : int
        Rollout ID for database logging.

    Returns
    -------
    CodeResult
        A dataclass containing the task, agent identifier, generated code, and timestamp.
    """
    # Set up task logger
    task_logger = logger.bind(task_id=seed_task.id, agent_id=agent_id)
    task_logger.info(
        "Starting containerized agent",
        output_dir=str(output_dir),
        task_preview=seed_task.prompt[:100],
    )

    # Use containerized Claude with automatic file collection
    # task_claude already imported above

    async with TaskClaude(
        seed_task.id, cfg, output_dir, seed_task, task_logger
    ) as claude:
        # Write system prompt inside container (before PATH isolation)
        claude.setup_system_prompt(system_prompt)

        # Execute Claude session using the containerized client
        message_sequence = []
        anthropic_request = {
            "prompt": seed_task.prompt,
            "options": f"containerized_claude_task_{seed_task.id}",
        }

        anthropic_log.log(request=anthropic_request, event="request_sent")

        await claude.query()
        seq_order = 0

        async for message in claude.receive_messages():
            anthropic_log.log(request=anthropic_request, event=safe_serialize(message))
            message_sequence.append(message)  # Store the actual message object
            # Only log to console, not to the JSON file
            # TODO: Consider a console-only logger for real-time updates

            seq_order += 1

            if isinstance(message, ResultMessage):
                task_logger.info(
                    "Containerized session completed",
                    duration_ms=message.duration_ms,
                    cost_usd=message.total_cost_usd,
                    is_error=message.is_error,
                )
                # Track rollout cost
                cost_tracker.add_rollout_cost(message.total_cost_usd)
                break

        # Copy files from container to host
        file_collection = await claude.collect_outputs()

    # Convert to grader format
    files_info = [
        FileInfo(path=fi["path"], content=fi["content"]) if isinstance(fi, dict) else fi
        for fi in file_collection
    ]

    timestamp = datetime.utcnow()
    return CodeResult(
        task=seed_task.prompt,
        task_id=seed_task.id,
        agent_id=agent_id,
        timestamp=timestamp,
        messages=message_sequence,
        files=files_info,
    )


async def optimize_prompts(
    *,
    anthropic_log,
    openai_client: LoggingOpenAIClient,
    seed_tasks: list[SeedTask],
    criteria: list[Criterion],
    cfg: OptimizerConfig,
    iterations: int = 3,
    rollouts_per_task: int = 2,
    max_parallel_rollouts: int | None = None,
    tasks_per_iteration: int | None = None,
    base_dir: Path,
) -> Path:
    """Run the prompt optimisation loop.

    This is the main entry point for running multiple iterations of the algorithm. It
    repeatedly executes batches of coding agents on the seed tasks in parallel,
    grades the generated solutions using OpenAI's Responses API, updates the system
    prompt using a prompt engineer (OpenAI o3), and logs results to JSONL files.

    Parameters
    ----------
    seed_tasks : List[SeedTask]
        The programming tasks to use as the benchmark for optimisation.
    iterations : int, optional
        The number of optimisation iterations to perform (default 3).
    rollouts_per_task : int, optional
        The number of coding agents to sample per task in each iteration (default 2).
    max_parallel_rollouts : int, optional
        Maximum number of concurrent coding agent rollouts (default from config).
    tasks_per_iteration : int, optional
        Number of tasks to randomly sample (with replacement) per iteration.
        If None, uses all seed tasks (default None).
    """
    if max_parallel_rollouts is None:
        max_parallel_rollouts = cfg.rollouts.max_parallel

    # Prepare API loggers for both OpenAI and Anthropic (keeping these for debugging)

    # Criteria already passed as parameter

    # Initialize the prompt engineer for the entire optimization process.
    feedback_mode = FeedbackMode(cfg.prompt_engineer.feedback_mode)
    if feedback_mode == FeedbackMode.SUMMARY:
        feedback_provider = PatternSummarizer(
            model=LoggingOpenAIModel(
                openai_client=openai_client,
                model=cfg.grader.model,
                context_window_tokens=cfg.tokens.max_context_tokens,
            ),
            # UGH
            truncation_manager=TruncationManager(cfg),
            max_file_pattern_analysis=cfg.truncation.max_file_pattern_analysis,
        )
    elif feedback_mode == FeedbackMode.STATS_ONLY:
        feedback_provider = StatsOnlyFeedbackProvider()
    elif feedback_mode == FeedbackMode.FULL_ROLLOUTS:
        feedback_provider = FullRolloutsFeedbackProvider()
    else:
        raise ValueError(f"Invalid {feedback_mode = }.")

    engineer = PromptEngineer(
        model=LoggingOpenAIModel(
            openai_client=openai_client,
            model=cfg.prompt_engineer.model,
            context_window_tokens=cfg.tokens.max_context_tokens,
            reasoning_effort=cfg.grader.reasoning_effort,
        ),
        feedback_provider=feedback_provider,
    )

    # Generate initial prompt without any rollout data
    prev_reasoning, prev_function_call, current_prompt = await engineer.propose_prompt()

    # Track prompts
    prompts_by_iteration = {0: current_prompt}

    # Create semaphore for controlling parallel rollouts
    rollout_semaphore = asyncio.Semaphore(max_parallel_rollouts)

    # Define the inner rollout function
    async def run_single_rollout(
        task: SeedTask,
        rollout_id: int,
        iteration: int,
    ) -> GradedCode:
        """Run a single rollout with semaphore control."""
        async with rollout_semaphore:
            # Create rollout directory structure
            rollout_dir = (
                base_dir / f"iter_{iteration:03d}" / task.id / f"agent_{rollout_id}"
            )
            rollout_dir.mkdir(parents=True, exist_ok=True)

            # Create work subdirectory for Claude
            work_dir = rollout_dir / "work"
            work_dir.mkdir(parents=True, exist_ok=True)

            # Run containerized Claude in work subdirectory
            code_result = await run_claude_code(
                task,
                current_prompt,
                agent_id=rollout_id,
                output_dir=work_dir,
                anthropic_log=anthropic_log,
                cfg=cfg,
            )

            # Save rollout data as JSON in agent directory
            rollout_data = {
                "task_id": task.id,
                "agent_id": rollout_id,
                "iteration": iteration,
                "timestamp": datetime.utcnow().isoformat(),
                "messages": [
                    asdict(msg) for msg in code_result.messages
                ],  # Convert Message objects to dicts
                "files": [f.model_dump() for f in code_result.files],
            }
            rollout_json_path = rollout_dir / "rollout.json"
            with open(rollout_json_path, "w") as f:
                json.dump(rollout_data, f, indent=2)

            try:
                grade = await grade_code(
                    code_result,
                    criteria,
                    model=LoggingOpenAIModel(
                        openai_client=openai_client,
                        model=cfg.grader.model,
                        context_window_tokens=cfg.tokens.max_context_tokens,
                        reasoning_effort=cfg.grader.reasoning_effort,
                    ),
                    cfg=cfg,
                )
            except ContextWindowExceededException as e:
                logger.warning(
                    "Skipping rollout due to context window exceeded",
                    task_id=e.task_id,
                    agent_id=e.agent_id,
                    iteration=iteration,
                    error=str(e),
                )
                # Save error info to grading.json
                grading_data = {
                    "error": "context_window_exceeded",
                    "error_message": str(e),
                    "grader_model": cfg.grader.model,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                with open(rollout_dir / "grading_error.json", "w") as f:
                    json.dump(grading_data, f, indent=2)

                # Return None to indicate this rollout should be excluded
                return None

            # Save grading results as JSON
            grading_data = {
                "overall_score": grade.overall_score,
                "overall_rationale": grade.overall_rationale,
                "axes": {
                    name: {
                        "score": score_rat.score,
                        "rationale": score_rat.rationale,
                    }
                    for name, score_rat in grade.axes.items()
                },
                "grader_model": cfg.grader.model,
                "timestamp": datetime.utcnow().isoformat(),
            }
            with open(rollout_dir / "grading.json", "w") as f:
                json.dump(grading_data, f, indent=2)

            # Extract cost from the last message if it's a ResultMessage
            total_cost = 0.0
            duration_ms = None
            is_error = False

            if code_result.messages:
                last_msg = code_result.messages[-1]
                if isinstance(last_msg, ResultMessage):
                    total_cost = last_msg.total_cost_usd
                    duration_ms = last_msg.duration_ms
                    is_error = last_msg.is_error

            # Add metrics to rollout data
            rollout_data["total_cost_usd"] = total_cost
            rollout_data["duration_ms"] = duration_ms
            rollout_data["is_error"] = is_error
            with open(rollout_json_path, "w") as f:
                json.dump(rollout_data, f, indent=2)

            logger.info(
                "Rollout completed",
                task_id=task.id,
                rollout_id=rollout_id,
                iteration=iteration,
                overall_score=grade.overall_score,
            )

            return GradedCode(code_result=code_result, grade=grade)

    # Log experiment configuration
    tasks_per_iter = (
        tasks_per_iteration if tasks_per_iteration is not None else len(seed_tasks)
    )
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
        iter_dir = base_dir / f"iter_{iteration:03d}"
        iter_dir.mkdir(parents=True, exist_ok=True)
        (iter_dir / "CLAUDE.md").write_text(current_prompt)

        # Randomly sample tasks with replacement
        iteration_tasks = random.choices(seed_tasks, k=tasks_per_iter)
        iter_logger.info(
            "Sampled tasks for iteration",
            sampled_count=tasks_per_iter,
            unique_tasks=len({task.id for task in iteration_tasks}),
            task_ids=[task.id for task in iteration_tasks],
        )

        # Create all rollout tasks for fully parallel execution
        # Each rollout runs: coding agent → grading → database storage
        # Semaphore controls max concurrent rollouts to prevent resource exhaustion
        rollout_futures = [
            run_single_rollout(task, rollout_id, iteration)
            for task in iteration_tasks
            for rollout_id in range(rollouts_per_task)
        ]

        iter_logger.info(
            "Starting parallel rollouts",
            total_rollouts=len(rollout_futures),
            max_parallel=max_parallel_rollouts,
        )

        # Execute all rollouts in parallel with semaphore-based concurrency control
        # Fail fast on any setup errors - don't continue if container setup fails
        all_rollouts_raw = []
        try:
            all_rollouts_raw = await asyncio.gather(
                *rollout_futures,
                return_exceptions=False,
            )
        except (asyncio.CancelledError, RuntimeError, OSError) as e:
            # Cancel all remaining tasks immediately
            iter_logger.error(
                "Critical failure during rollouts - cancelling all tasks",
                error=str(e),
                error_type=type(e).__name__,
            )

            # Wait a moment for cancellation to complete
            await asyncio.sleep(0.1)

            # Exit the entire program immediately
            iter_logger.error(
                "FATAL: Container setup failed - terminating optimization",
                error=str(e),
            )
            import sys

            sys.exit(1)

        # Filter out None values (failed grading due to context window)
        all_rollouts = [r for r in all_rollouts_raw if r is not None]
        skipped_count = len(all_rollouts_raw) - len(all_rollouts)

        if skipped_count > 0:
            iter_logger.warning(
                "Some rollouts skipped due to context window issues",
                total_rollouts=len(all_rollouts_raw),
                successful_rollouts=len(all_rollouts),
                skipped_rollouts=skipped_count,
            )

        # Check if we have any successful rollouts
        if not all_rollouts:
            iter_logger.error(
                "No successful rollouts in this iteration",
                iteration=iteration,
            )
            continue

        iter_logger.info(
            "All rollouts completed",
            completed_rollouts=len(all_rollouts),
            skipped_rollouts=skipped_count,
        )

        # Display simple metrics to CLI
        overall_scores = [
            graded_code.grade.overall_score for graded_code in all_rollouts
        ]
        avg_overall = (
            sum(overall_scores) / len(overall_scores) if overall_scores else 0.0
        )
        iter_logger.info(
            "Iteration complete",
            average_overall_score=round(avg_overall, 2),
        )

        # Track score evolution for this iteration
        score_tracker.add_iteration(iteration, all_rollouts)

        # Generate and save score evolution report and plots after each iteration
        evolution_report = score_tracker.generate_report(base_dir, base_dir / "logs")
        report_path = base_dir / f"score_evolution_iter_{iteration}.txt"
        report_path.write_text(evolution_report)
        iter_logger.info(
            "Score evolution report generated",
            report_path=str(report_path),
            iteration=iteration,
        )

        # Store pattern analysis in database and prepare feedback for PE
        # rollout_ids = db.get_rollouts_for_iteration(run_id, iteration)
        # rollout_db_ids = [r.id for r in rollout_ids]

        await engineer.add_result(
            prev_reasoning,
            prev_function_call,
            current_prompt,
            all_rollouts,
        )

        # Generate next prompt using PE (if not the last iteration)
        if iteration < iterations:
            (
                prev_reasoning,
                prev_function_call,
                new_prompt,
            ) = await engineer.propose_prompt()

            # Store new system prompt
            prompts_by_iteration[iteration + 1] = new_prompt
            current_prompt = new_prompt

    # Save all prompts to a file
    with open(base_dir / "prompts.json", "w") as f:
        json.dump(prompts_by_iteration, f, indent=2)

    logger.info("Optimization complete", logs_directory=str(base_dir))
    return base_dir


def main() -> None:
    """Entry point for standalone execution."""
    parser = argparse.ArgumentParser(
        description="Parallel prompt optimization system for coding agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --iterations 5 --rollouts-per-task 3
  %(prog)s --mode summary --iterations 1 --rollouts-per-task 1
  %(prog)s --mode stats_only --iterations 3 --rollouts-per-task 2
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
        "--max-parallel",
        type=int,
        default=None,
        help="Maximum parallel rollouts (default: from config file)",
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

    # Load configuration
    cfg = OptimizerConfig.from_file()

    # Load tasks and criteria from YAML
    logger.info("Loading YAML files")
    yaml_loader = load_yaml_files(cfg.seeds_file, cfg.graders_file)

    # Load tasks - yaml_loader.seeds_data already returns the right type
    seed_tasks = list(yaml_loader.seeds_data)

    # Load grading criteria
    criteria = []
    for grader_data in yaml_loader.graders_data:
        criteria.append(
            Criterion(
                name=grader_data.id,
                description=grader_data.description,
            )
        )

    run_prefix = datetime.utcnow().strftime("%Y-%m-%d-%H%M%S")
    base_dir = (Path("./agent_output") / run_prefix).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    openai_client = LoggingOpenAIClient(
        openai_client=OpenAI(),
        jsonl_logger=JSONLLogger(base_dir / "openai_api_log.jsonl"),
    )
    # Run the optimisation loop
    anthropic_log = JSONLLogger(base_dir / "anthropic_api_log.jsonl")
    run_dir = asyncio.run(
        optimize_prompts(
            anthropic_log=anthropic_log,
            openai_client=openai_client,
            seed_tasks=seed_tasks,
            criteria=criteria,
            cfg=cfg,
            iterations=args.iterations,
            rollouts_per_task=args.rollouts_per_task,
            max_parallel_rollouts=args.max_parallel,
            tasks_per_iteration=args.tasks_per_iteration,
            base_dir=base_dir,
        ),
    )

    # Generate final score evolution report
    final_evolution_report = score_tracker.generate_report(run_dir, run_dir)
    final_report_path = run_dir / "final_score_evolution_report.txt"
    final_report_path.write_text(final_evolution_report)

    print("\n" + "=" * 60)
    print(final_evolution_report)
    print("=" * 60)

    logger.info(
        "Score evolution report generated",
        report_path=str(final_report_path),
        run_directory=str(run_dir),
    )
    cost_tracker.report_final_cost()


if __name__ == "__main__":
    main()

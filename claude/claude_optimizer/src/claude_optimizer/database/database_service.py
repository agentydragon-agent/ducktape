import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from claude_code_sdk import AssistantMessage, ResultMessage, SystemMessage, UserMessage

from claude_optimizer.core.logging_utils import DualOutputLogging
from claude_optimizer.database.models import (
    Base,
    GraderFacetResult,
    GraderRun,
    GradingCriteria,
    OptimizationRun,
    Rollout,
    RolloutFile,
    RolloutMessage,
    SeedTask,
    SystemPrompt,
)

logger = DualOutputLogging.get_logger()


def init_db(database_url: str = "sqlite:///optimizer.db") -> sessionmaker:
    engine = create_engine(database_url, echo=False)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return SessionLocal


def create_optimization_run(
    session: Session,
    *,
    total_iterations: int,
    config_snapshot: dict[str, Any],
) -> int:
    run = OptimizationRun(
        start_time=datetime.utcnow(),
        base_output_dir="",
        total_iterations=total_iterations,
        config_snapshot=json.dumps(config_snapshot),
        status="running",
    )
    session.add(run)
    session.commit()
    logger.info("Created optimization run", run_id=run.id)
    return run.id


def complete_optimization_run(session: Session, run_id: int) -> None:
    run = session.query(OptimizationRun).filter_by(id=run_id).first()
    run.end_time = datetime.utcnow()
    run.status = "completed"
    session.commit()
    logger.info("Completed optimization run", run_id=run_id)


def create_system_prompt(
    session: Session,
    *,
    run_id: int,
    iteration: int,
    content: str,
    prompt_engineer_reasoning: str | None = None,
) -> int:
    content_hash = SystemPrompt.compute_content_hash(content)
    existing = (
        session.query(SystemPrompt)
        .filter_by(run_id=run_id, content_hash=content_hash)
        .first()
    )
    if existing:
        logger.info(
            "Reusing existing system prompt",
            prompt_id=existing.id,
            iteration=iteration,
            content_hash=content_hash[:8],
        )
        return existing.id
    prompt = SystemPrompt(
        run_id=run_id,
        iteration=iteration,
        content=content,
        content_hash=content_hash,
        prompt_engineer_reasoning=prompt_engineer_reasoning,
    )
    session.add(prompt)
    session.commit()
    logger.info("Created system prompt", prompt_id=prompt.id, iteration=iteration)
    return prompt.id


def create_rollout(
    session: Session,
    *,
    run_id: int,
    iteration: int,
    seed_task_db_id: int,
    agent_id: str,
    system_prompt_id: int,
    output_dir_path: str,
) -> int:
    rollout = Rollout(
        run_id=run_id,
        iteration=iteration,
        task_id=seed_task_db_id,
        agent_id=agent_id,
        system_prompt_id=system_prompt_id,
        start_time=datetime.utcnow(),
        output_dir_path=output_dir_path,
    )
    session.add(rollout)
    session.commit()
    logger.info(
        "Started rollout",
        rollout_id=rollout.id,
        iteration=iteration,
        task_id=seed_task_db_id,
        agent_id=agent_id,
    )
    return rollout.id


def complete_rollout(
    session: Session,
    *,
    rollout_id: int,
    total_cost_usd: float | None = None,
    is_error: bool = False,
    duration_ms: int | None = None,
) -> None:
    rollout = session.query(Rollout).filter_by(id=rollout_id).first()
    if rollout:
        rollout.end_time = datetime.utcnow()
        rollout.total_cost_usd = total_cost_usd
        rollout.is_error = is_error
        rollout.duration_ms = duration_ms
        session.commit()
        logger.info(
            "Completed rollout",
            rollout_id=rollout_id,
            total_cost_usd=total_cost_usd,
            is_error=is_error,
            duration_ms=duration_ms,
        )


def log_rollout_message(
    session: Session,
    *,
    rollout_id: int,
    sequence_order: int,
    message_type: str,
    message_content: dict[str, Any] | SystemMessage | UserMessage | AssistantMessage | ResultMessage | str,
) -> None:
    try:
        if hasattr(message_content, "model_dump"):
            content_json = json.dumps(message_content.model_dump())
        elif hasattr(message_content, "__dict__"):
            content_json = json.dumps(message_content.__dict__)
        elif isinstance(message_content, dict):
            content_json = json.dumps(message_content)
        else:
            content_json = json.dumps(str(message_content))
    except Exception as e:
        logger.warning(
            "Failed to serialize message content",
            error=str(e),
            message_type=message_type,
        )
        content_json = json.dumps({"error": "Failed to serialize", "type": str(type(message_content))})
    message = RolloutMessage(
        rollout_id=rollout_id,
        sequence_order=sequence_order,
        message_type=message_type,
        content=content_json,
        timestamp=datetime.utcnow(),
    )
    session.add(message)
    session.commit()


def store_rollout_files(
    session: Session,
    *,
    rollout_id: int,
    files_info: list[dict[str, str]],
    rollout_dir: Path,
) -> None:
    for file_info in files_info:
        relative_path = file_info["path"]
        content = file_info["content"]
        if content == "<<not a plaintext file>>":
            logger.info(
                "Skipping binary file storage",
                rollout_id=rollout_id,
                file_path=relative_path,
            )
            continue
        is_truncated = "[TRUNCATED FOR API LIMITS:" in content
        absolute_path = rollout_dir / relative_path
        if absolute_path.exists():
            try:
                file_hash = RolloutFile.compute_file_hash(absolute_path)
                file_size = absolute_path.stat().st_size
            except Exception as e:
                logger.warning(
                    "Failed to compute file hash",
                    file_path=str(absolute_path),
                    error=str(e),
                )
                continue
        else:
            file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            file_size = len(content.encode("utf-8"))
        rollout_file = RolloutFile(
            rollout_id=rollout_id,
            relative_path=relative_path,
            absolute_path=str(absolute_path),
            content_sha256=file_hash,
            file_size=file_size,
            is_truncated=is_truncated,
            is_binary=False,
        )
        session.add(rollout_file)
    session.commit()
    logger.info("Stored rollout files", rollout_id=rollout_id, file_count=len(files_info))


def store_grading_results(
    session: Session,
    *,
    rollout_id: int,
    overall_score: float,
    overall_rationale: str,
    facet_scores: dict[str, dict[str, Any]],
    grader_model: str = "o3",
    grader_reasoning: str | None = None,
) -> int:
    grader_run = GraderRun(
        rollout_id=rollout_id,
        overall_score=overall_score,
        overall_rationale=overall_rationale,
        grader_model=grader_model,
        grader_reasoning=grader_reasoning,
    )
    session.add(grader_run)
    session.flush()
    for order, (facet_name, facet_data) in enumerate(facet_scores.items()):
        criterion = (
            session.query(GradingCriteria)
            .filter_by(name=facet_name, is_active=True)
            .first()
        )
        if not criterion:
            logger.warning("Grading criterion not found", facet_name=facet_name)
            continue
        facet_result = GraderFacetResult(
            grader_run_id=grader_run.id,
            criterion_id=criterion.id,
            score=facet_data["score"],
            rationale=facet_data["rationale"],
            facet_order=order,
        )
        session.add(facet_result)
    session.commit()
    logger.info(
        "Stored grading results",
        grader_run_id=grader_run.id,
        rollout_id=rollout_id,
        overall_score=overall_score,
        facet_count=len(facet_scores),
    )
    return grader_run.id


def get_active_seed_tasks(session: Session) -> list[SeedTask]:
    return session.query(SeedTask).filter_by(is_active=True).all()


def get_active_grading_criteria(session: Session) -> list[GradingCriteria]:
    return session.query(GradingCriteria).filter_by(is_active=True).all()


def get_rollouts_for_iteration(session: Session, run_id: int, iteration: int) -> list[Rollout]:
    return (
        session.query(Rollout)
        .filter_by(run_id=run_id, iteration=iteration)
        .all()
    )

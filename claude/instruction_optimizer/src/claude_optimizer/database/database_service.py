"""Database service for storing optimizer data instead of JSONL files."""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from claude_code_sdk import AssistantMessage, ResultMessage, SystemMessage, UserMessage

from claude_optimizer.core.logging_utils import DualOutputLogging
from claude_optimizer.database.models import (
    GraderFacetResult,
    GraderRun,
    GradingCriteria,
    OptimizationRun,
    PatternAnalysis,
    PatternAnalysisRollout,
    Rollout,
    RolloutFile,
    RolloutMessage,
    SeedTask,
    SystemPrompt,
    get_db_session,
)

logger = DualOutputLogging.get_logger()


class DatabaseService:
    """Service for managing database operations during optimization runs."""
    
    def __init__(self):
        self.current_run_id: Optional[int] = None
        self.current_rollout_id: Optional[int] = None
    
    def create_optimization_run(
        self, 
        base_output_dir: str,
        total_iterations: int,
        config_snapshot: dict[str, Any],
    ) -> int:
        """Create a new optimization run record.
        
        Returns:
            The ID of the created optimization run
        """
        with get_db_session() as session:
            run = OptimizationRun(
                start_time=datetime.utcnow(),
                base_output_dir=base_output_dir,
                total_iterations=total_iterations,
                config_snapshot=json.dumps(config_snapshot),
                status='running',
            )
            session.add(run)
            session.commit()
            self.current_run_id = run.id
            
            logger.info(
                "Created optimization run",
                run_id=run.id,
                base_output_dir=base_output_dir,
                total_iterations=total_iterations,
            )
            
            return run.id
    
    def complete_optimization_run(self, run_id: Optional[int] = None):
        """Mark an optimization run as completed."""
        run_id = run_id or self.current_run_id
        if not run_id:
            logger.warning("No run ID available to complete")
            return
            
        with get_db_session() as session:
            run = session.query(OptimizationRun).filter_by(id=run_id).first()
            if run:
                run.end_time = datetime.utcnow()
                run.status = 'completed'
                session.commit()
                
                logger.info("Completed optimization run", run_id=run_id)
    
    def create_system_prompt(
        self,
        run_id: int,
        iteration: int,
        content: str,
        prompt_engineer_reasoning: Optional[str] = None,
    ) -> int:
        """Create a system prompt record.
        
        Returns:
            The ID of the created system prompt
        """
        content_hash = SystemPrompt.compute_content_hash(content)
        
        with get_db_session() as session:
            # Check if this exact prompt already exists for this run
            existing = session.query(SystemPrompt).filter_by(
                run_id=run_id,
                content_hash=content_hash,
            ).first()
            
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
            
            logger.info(
                "Created system prompt",
                prompt_id=prompt.id,
                iteration=iteration,
                content_hash=content_hash[:8],
                content_length=len(content),
            )
            
            return prompt.id
    
    def create_rollout(
        self,
        run_id: int,
        iteration: int,
        task_id: str,
        agent_id: str,
        system_prompt_id: int,
        output_dir_path: str,
    ) -> int:
        """Create a rollout record.
        
        Returns:
            The ID of the created rollout
        """
        with get_db_session() as session:
            # Get the task ID from database
            task = session.query(SeedTask).filter_by(task_id=task_id, is_active=True).first()
            if not task:
                raise ValueError(f"Task {task_id} not found in database")
            
            rollout = Rollout(
                run_id=run_id,
                iteration=iteration,
                task_id=task.id,
                agent_id=agent_id,
                system_prompt_id=system_prompt_id,
                start_time=datetime.utcnow(),
                output_dir_path=output_dir_path,
            )
            session.add(rollout)
            session.commit()
            self.current_rollout_id = rollout.id
            
            logger.info(
                "Started rollout",
                rollout_id=rollout.id,
                iteration=iteration,
                task_id=task_id,
                agent_id=agent_id,
            )
            
            return rollout.id
    
    def complete_rollout(
        self,
        rollout_id: int,
        total_cost_usd: Optional[float] = None,
        is_error: bool = False,
        duration_ms: Optional[int] = None,
    ):
        """Complete a rollout record with final metrics."""
        with get_db_session() as session:
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
        self,
        rollout_id: int,
        sequence_order: int,
        message_type: str,
        message_content: Union[dict[str, Any], SystemMessage, UserMessage, AssistantMessage, ResultMessage, str],
    ):
        """Log a message from the Claude SDK conversation."""
        try:
            # Convert message to JSON-serializable format
            if hasattr(message_content, 'model_dump'):
                content_json = json.dumps(message_content.model_dump())
            elif hasattr(message_content, '__dict__'):
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
        
        with get_db_session() as session:
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
        self,
        rollout_id: int,
        files_info: list[dict[str, str]],
        rollout_dir: Path,
    ):
        """Store file information for a rollout."""
        with get_db_session() as session:
            for file_info in files_info:
                relative_path = file_info["path"]
                content = file_info["content"]
                
                # Skip binary files and truncated markers
                if content == "<<not a plaintext file>>":
                    logger.info(
                        "Skipping binary file storage",
                        rollout_id=rollout_id,
                        file_path=relative_path,
                    )
                    continue
                
                # Determine if content was truncated
                is_truncated = "[TRUNCATED FOR API LIMITS:" in content
                
                # Calculate absolute path and file hash
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
                    # File doesn't exist on disk, compute hash from content
                    file_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
                    file_size = len(content.encode('utf-8'))
                
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
            
            logger.info(
                "Stored rollout files",
                rollout_id=rollout_id,
                file_count=len(files_info),
            )
    
    def store_grading_results(
        self,
        rollout_id: int,
        overall_score: float,
        overall_rationale: str,
        facet_scores: dict[str, dict[str, Any]],
        grader_model: str = "o3",
        grader_reasoning: Optional[str] = None,
    ) -> int:
        """Store grading results for a rollout.
        
        Args:
            rollout_id: ID of the rollout being graded
            overall_score: Overall score (0-10)
            overall_rationale: Overall grading rationale
            facet_scores: Dict mapping facet names to score/rationale dicts
            grader_model: Model used for grading
            grader_reasoning: Optional JSON reasoning from OpenAI
            
        Returns:
            The ID of the created grader run
        """
        with get_db_session() as session:
            # Create grader run
            grader_run = GraderRun(
                rollout_id=rollout_id,
                overall_score=overall_score,
                overall_rationale=overall_rationale,
                grader_model=grader_model,
                grader_reasoning=grader_reasoning,
            )
            session.add(grader_run)
            session.flush()  # Get the ID
            
            # Create facet results
            for order, (facet_name, facet_data) in enumerate(facet_scores.items()):
                # Find the grading criteria
                criterion = session.query(GradingCriteria).filter_by(
                    name=facet_name,
                    is_active=True,
                ).first()
                
                if not criterion:
                    logger.warning(
                        "Grading criterion not found",
                        facet_name=facet_name,
                    )
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
    
    def store_pattern_analysis(
        self,
        run_id: int,
        iteration: int,
        rollout_ids: list[int],
        summary_text: str,
        tokens_used: Optional[int] = None,
        analysis_reasoning: Optional[str] = None,
    ) -> int:
        """Store pattern analysis results.
        
        Returns:
            The ID of the created pattern analysis
        """
        with get_db_session() as session:
            analysis = PatternAnalysis(
                run_id=run_id,
                iteration=iteration,
                input_rollout_count=len(rollout_ids),
                summary_text=summary_text,
                tokens_used=tokens_used,
                analysis_reasoning=analysis_reasoning,
            )
            session.add(analysis)
            session.flush()  # Get the ID
            
            # Link rollouts to analysis
            for order, rollout_id in enumerate(rollout_ids):
                pattern_rollout = PatternAnalysisRollout(
                    pattern_analysis_id=analysis.id,
                    rollout_id=rollout_id,
                    rollout_order=order,
                )
                session.add(pattern_rollout)
            
            session.commit()
            
            logger.info(
                "Stored pattern analysis",
                analysis_id=analysis.id,
                iteration=iteration,
                rollout_count=len(rollout_ids),
                summary_length=len(summary_text),
            )
            
            return analysis.id
    
    def get_active_seed_tasks(self) -> list[SeedTask]:
        """Get all active seed tasks."""
        with get_db_session() as session:
            return session.query(SeedTask).filter_by(is_active=True).all()
    
    def get_active_grading_criteria(self) -> list[GradingCriteria]:
        """Get all active grading criteria."""
        with get_db_session() as session:
            return session.query(GradingCriteria).filter_by(is_active=True).all()
    
    def get_rollouts_for_iteration(self, run_id: int, iteration: int) -> list[Rollout]:
        """Get all rollouts for a specific iteration."""
        with get_db_session() as session:
            return session.query(Rollout).filter_by(
                run_id=run_id,
                iteration=iteration,
            ).all()


# Global database service instance
db_service = DatabaseService()
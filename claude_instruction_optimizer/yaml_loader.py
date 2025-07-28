"""YAML loader with content hashing and database synchronization."""

import yaml
from pathlib import Path
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from database import SeedTask, GradingCriteria, get_db_session
from logging_utils import DualOutputLogging

logger = DualOutputLogging.get_logger()


class YamlLoader:
    """Handles loading and syncing YAML files to database."""
    
    def __init__(self, seeds_yaml_path: Path, graders_yaml_path: Path):
        self.seeds_yaml_path = Path(seeds_yaml_path)
        self.graders_yaml_path = Path(graders_yaml_path)
        
    def load_and_sync_all(self, session: Optional[Session] = None) -> Dict[str, int]:
        """Load and sync both seeds and graders YAML files to database.
        
        Returns:
            Dict with counts: {'seeds_added': N, 'seeds_updated': N, 'graders_added': N, 'graders_updated': N}
        """
        if session is None:
            session = get_db_session()
            should_close = True
        else:
            should_close = False
            
        try:
            stats = {}
            
            # Sync seed tasks
            seed_stats = self.sync_seed_tasks(session)
            stats.update(seed_stats)
            
            # Sync grading criteria
            grader_stats = self.sync_grading_criteria(session)
            stats.update(grader_stats)
            
            session.commit()
            
            logger.info(
                "YAML sync completed",
                seeds_added=stats.get('seeds_added', 0),
                seeds_updated=stats.get('seeds_updated', 0),
                graders_added=stats.get('graders_added', 0),
                graders_updated=stats.get('graders_updated', 0)
            )
            
            return stats
            
        except Exception as e:
            session.rollback()
            logger.error("YAML sync failed", error=str(e))
            raise
        finally:
            if should_close:
                session.close()
    
    def sync_seed_tasks(self, session: Session) -> Dict[str, int]:
        """Sync seed tasks from YAML to database.
        
        Returns:
            Dict with 'seeds_added' and 'seeds_updated' counts
        """
        if not self.seeds_yaml_path.exists():
            logger.warning("Seeds YAML not found", path=str(self.seeds_yaml_path))
            return {'seeds_added': 0, 'seeds_updated': 0}
            
        # Load YAML content
        with open(self.seeds_yaml_path, 'r', encoding='utf-8') as f:
            yaml_data = yaml.safe_load(f)
            
        if not isinstance(yaml_data, list):
            raise ValueError(f"Seeds YAML must contain a list of tasks, got {type(yaml_data)}")
            
        seeds_added = 0
        seeds_updated = 0
        
        for task_data in yaml_data:
            if not isinstance(task_data, dict):
                logger.warning("Skipping invalid task data", data=task_data)
                continue
                
            task_id = task_data.get('id')
            prompt = task_data.get('prompt')
            description = task_data.get('description', '')
            
            if not task_id or not prompt:
                logger.warning("Skipping task missing id or prompt", task_data=task_data)
                continue
                
            # Compute content hash
            content_hash = SeedTask.compute_content_hash(prompt, description)
            
            # Check if task exists
            existing_task = session.query(SeedTask).filter_by(task_id=task_id).first()
            
            if existing_task is None:
                # Create new task
                new_task = SeedTask(
                    task_id=task_id,
                    prompt=prompt,
                    description=description,
                    content_hash=content_hash,
                    is_active=True
                )
                session.add(new_task)
                seeds_added += 1
                
                logger.info(
                    "Added new seed task",
                    task_id=task_id,
                    content_hash=content_hash[:8]
                )
                
            elif existing_task.content_hash != content_hash:
                # Update existing task
                existing_task.prompt = prompt
                existing_task.description = description
                existing_task.content_hash = content_hash
                existing_task.is_active = True
                seeds_updated += 1
                
                logger.info(
                    "Updated seed task",
                    task_id=task_id,
                    old_hash=existing_task.content_hash[:8],
                    new_hash=content_hash[:8]
                )
                
            else:
                # Task unchanged, just ensure it's active
                if not existing_task.is_active:
                    existing_task.is_active = True
                    logger.info("Reactivated seed task", task_id=task_id)
                
        return {'seeds_added': seeds_added, 'seeds_updated': seeds_updated}
    
    def sync_grading_criteria(self, session: Session) -> Dict[str, int]:
        """Sync grading criteria from YAML to database.
        
        Returns:
            Dict with 'graders_added' and 'graders_updated' counts
        """
        if not self.graders_yaml_path.exists():
            logger.warning("Graders YAML not found", path=str(self.graders_yaml_path))
            return {'graders_added': 0, 'graders_updated': 0}
            
        # Load YAML content
        with open(self.graders_yaml_path, 'r', encoding='utf-8') as f:
            yaml_data = yaml.safe_load(f)
            
        # Handle both old format (list) and new format (dict with 'graders' key)
        if isinstance(yaml_data, dict) and 'graders' in yaml_data:
            graders_list = yaml_data['graders']
        elif isinstance(yaml_data, list):
            graders_list = yaml_data
        else:
            raise ValueError(f"Graders YAML must contain 'graders' key or be a list, got {type(yaml_data)}")
            
        graders_added = 0
        graders_updated = 0
        
        for grader_data in graders_list:
            if not isinstance(grader_data, dict):
                logger.warning("Skipping invalid grader data", data=grader_data)
                continue
                
            name = grader_data.get('name')
            description = grader_data.get('description', '')
            evaluation_criteria = grader_data.get('evaluation_criteria', '')
            
            if not name:
                logger.warning("Skipping grader missing name", grader_data=grader_data)
                continue
                
            # Compute content hash
            content_hash = GradingCriteria.compute_content_hash(description, evaluation_criteria)
            
            # Check if criteria exists
            existing_criteria = session.query(GradingCriteria).filter_by(name=name).first()
            
            if existing_criteria is None:
                # Create new criteria
                new_criteria = GradingCriteria(
                    name=name,
                    description=description,
                    evaluation_criteria=evaluation_criteria,
                    content_hash=content_hash,
                    is_active=True
                )
                session.add(new_criteria)
                graders_added += 1
                
                logger.info(
                    "Added new grading criteria",
                    name=name,
                    content_hash=content_hash[:8]
                )
                
            elif existing_criteria.content_hash != content_hash:
                # Update existing criteria
                existing_criteria.description = description
                existing_criteria.evaluation_criteria = evaluation_criteria
                existing_criteria.content_hash = content_hash
                existing_criteria.is_active = True
                graders_updated += 1
                
                logger.info(
                    "Updated grading criteria",
                    name=name,
                    old_hash=existing_criteria.content_hash[:8],
                    new_hash=content_hash[:8]
                )
                
            else:
                # Criteria unchanged, just ensure it's active
                if not existing_criteria.is_active:
                    existing_criteria.is_active = True
                    logger.info("Reactivated grading criteria", name=name)
                
        return {'graders_added': graders_added, 'graders_updated': graders_updated}
    
    def get_active_seed_tasks(self, session: Optional[Session] = None) -> List[SeedTask]:
        """Get all active seed tasks from database."""
        if session is None:
            session = get_db_session()
            should_close = True
        else:
            should_close = False
            
        try:
            tasks = session.query(SeedTask).filter_by(is_active=True).all()
            return tasks
        finally:
            if should_close:
                session.close()
    
    def get_active_grading_criteria(self, session: Optional[Session] = None) -> List[GradingCriteria]:
        """Get all active grading criteria from database."""
        if session is None:
            session = get_db_session()
            should_close = True
        else:
            should_close = False
            
        try:
            criteria = session.query(GradingCriteria).filter_by(is_active=True).all()
            return criteria
        finally:
            if should_close:
                session.close()
    
    def deactivate_missing_tasks(self, session: Session, yaml_task_ids: List[str]) -> int:
        """Deactivate tasks that are no longer in YAML files.
        
        Args:
            session: Database session
            yaml_task_ids: List of task IDs found in current YAML
            
        Returns:
            Number of tasks deactivated
        """
        deactivated_count = 0
        
        # Find active tasks not in current YAML
        missing_tasks = (
            session.query(SeedTask)
            .filter(SeedTask.is_active == True)
            .filter(~SeedTask.task_id.in_(yaml_task_ids))
            .all()
        )
        
        for task in missing_tasks:
            task.is_active = False
            deactivated_count += 1
            
            logger.info(
                "Deactivated missing seed task",
                task_id=task.task_id
            )
            
        return deactivated_count
    
    def deactivate_missing_criteria(self, session: Session, yaml_criteria_names: List[str]) -> int:
        """Deactivate criteria that are no longer in YAML files.
        
        Args:
            session: Database session
            yaml_criteria_names: List of criteria names found in current YAML
            
        Returns:
            Number of criteria deactivated
        """
        deactivated_count = 0
        
        # Find active criteria not in current YAML
        missing_criteria = (
            session.query(GradingCriteria)
            .filter(GradingCriteria.is_active == True)
            .filter(~GradingCriteria.name.in_(yaml_criteria_names))
            .all()
        )
        
        for criteria in missing_criteria:
            criteria.is_active = False
            deactivated_count += 1
            
            logger.info(
                "Deactivated missing grading criteria",
                name=criteria.name
            )
            
        return deactivated_count


def load_yaml_files(
    seeds_yaml_path: str = "seeds.yaml",
    graders_yaml_path: str = "graders_consolidated.yaml"
) -> YamlLoader:
    """Create and return a configured YAML loader."""
    return YamlLoader(
        seeds_yaml_path=Path(seeds_yaml_path),
        graders_yaml_path=Path(graders_yaml_path)
    )
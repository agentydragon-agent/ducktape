"""YAML loader with content hashing and database synchronization."""

import json
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session
from pydantic import BaseModel, validator

from database import SeedTask, TaskRepository, GradingCriteria, get_db_session
from logging_utils import DualOutputLogging

logger = DualOutputLogging.get_logger()


class TaskDataModel(BaseModel):
    """Pydantic model for task data validation."""
    id: str
    prompt: str
    dependencies: List[str]
    git_repos: Dict[str, Any]
    allowed_tools: List[str]
    pre_task_setup_script: Optional[str] = None
    
    @validator('id')
    def validate_id(cls, v):
        if not v or not v.strip():
            raise ValueError("Task ID cannot be empty")
        return v.strip()
    
    @validator('prompt') 
    def validate_prompt(cls, v):
        if not v or not v.strip():
            raise ValueError("Task prompt cannot be empty")
        return v.strip()
    
    @validator('dependencies')
    def validate_dependencies(cls, v):
        if not isinstance(v, list):
            raise ValueError("Dependencies must be a list")
        return v
    
    @validator('allowed_tools')
    def validate_allowed_tools(cls, v):
        if not isinstance(v, list):
            raise ValueError("Allowed tools must be a list")
        return v


class YamlLoader:
    """Handles loading and syncing YAML files to database."""
    
    def __init__(self, seeds_yaml_path: Path, graders_yaml_path: Path):
        self.seeds_yaml_path = Path(seeds_yaml_path)
        self.graders_yaml_path = Path(graders_yaml_path)
        self._seeds_data = None
        self._graders_data = None
        
    def _load_yaml_file(self, path: Path, file_type: str) -> Any:
        """Load and cache YAML file content."""
        if not path.exists():
            raise FileNotFoundError(f"FATAL: {file_type} YAML file not found: {path}. Check your config.yaml!")
            
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    @property
    def seeds_data(self) -> List[Dict]:
        """Load seeds YAML data (cached)."""
        if self._seeds_data is None:
            data = self._load_yaml_file(self.seeds_yaml_path, "Seeds")
            if not isinstance(data, list):
                raise ValueError(f"Seeds YAML must contain a list of tasks, got {type(data)}")
            self._seeds_data = data
        return self._seeds_data
    
    @property 
    def graders_data(self) -> List[Dict]:
        """Load graders YAML data (cached)."""
        if self._graders_data is None:
            data = self._load_yaml_file(self.graders_yaml_path, "Graders")
            if not isinstance(data, dict) or 'graders' not in data:
                raise ValueError(f"Graders YAML must be a dict with 'graders' key, got {type(data)}")
            self._graders_data = data['graders']
        return self._graders_data
        
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
        seeds_added = 0
        seeds_updated = 0
        
        for task_data in self.seeds_data:
            # Validate with Pydantic - will crash on invalid data
            try:
                validated_task = TaskDataModel(**task_data)
            except Exception as e:
                logger.error("Invalid task data - failing fast", task_data=task_data, error=str(e))
                raise ValueError(f"Task validation failed: {e}") from e
            
            # Extract validated fields
            task_id = validated_task.id
            prompt = validated_task.prompt
            dependencies = validated_task.dependencies
            git_repos = validated_task.git_repos
            allowed_tools = validated_task.allowed_tools
            pre_task_setup_script = validated_task.pre_task_setup_script
            
            # Serialize for storage
            dependencies_json = json.dumps(dependencies)
            git_repos_json = json.dumps(git_repos) if git_repos else '{}'
            allowed_tools_json = json.dumps(allowed_tools)
                
            # Compute content hash with available fields in database model
            content_hash = SeedTask.compute_content_hash(
                prompt=prompt,
                git_repos=git_repos_json,
                allowed_tools=allowed_tools_json,
                dependencies=dependencies_json,
                pre_task_setup_script=pre_task_setup_script
            )
            
            # Check if task exists
            existing_task = session.query(SeedTask).filter_by(task_id=task_id).first()
            
            if existing_task is None:
                # Create new task
                new_task = SeedTask(
                    task_id=task_id,
                    prompt=prompt,
                    git_repos=git_repos_json,
                    allowed_tools=allowed_tools_json,
                    dependencies=dependencies_json,
                    pre_task_setup_script=pre_task_setup_script,
                    content_hash=content_hash,
                    is_active=True
                )
                session.add(new_task)
                session.flush()  # Get the task ID for repository sync
                seeds_added += 1
                
                # Sync repository requirements
                if git_repos:
                    self._sync_task_repositories(session, new_task, git_repos)
                
                logger.info(
                    "Added new seed task",
                    task_id=task_id,
                    dependencies=dependencies,
                    content_hash=content_hash[:8]
                )
                
            elif existing_task.content_hash != content_hash:
                # Update existing task
                existing_task.prompt = prompt
                existing_task.git_repos = git_repos_json
                existing_task.allowed_tools = allowed_tools_json
                existing_task.dependencies = dependencies_json
                existing_task.pre_task_setup_script = pre_task_setup_script
                existing_task.content_hash = content_hash
                existing_task.is_active = True
                seeds_updated += 1
                
                # Clear and re-sync repository requirements
                session.query(TaskRepository).filter_by(task_id=existing_task.id).delete()
                session.flush()
                if git_repos:
                    self._sync_task_repositories(session, existing_task, git_repos)
                
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
        graders_added = 0
        graders_updated = 0
        
        for grader_data in self.graders_data:
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
    
    def _sync_task_repositories(self, session: Session, task: SeedTask, git_repos: Dict[str, Any]):
        """Sync repository requirements for a task."""
        for repo_url, repo_config in git_repos.items():
            if not isinstance(repo_config, dict):
                raise ValueError(f"Repository config for {repo_url} must be dict with 'commit' and 'main' fields")
            if 'commit' not in repo_config:
                raise ValueError(f"Repository config for {repo_url} missing required 'commit' field")
            if 'main' not in repo_config:
                raise ValueError(f"Repository config for {repo_url} missing required 'main' field")
                
            commit = repo_config['commit']
            is_main = repo_config['main']
            
            # Create repository requirement
            task_repo = TaskRepository(
                task_id=task.id,
                repo_url=repo_url,
                required_commit=commit,
                is_main_repo=is_main,
                mount_path=f"/git/{repo_url}"
            )
            session.add(task_repo)


def load_yaml_files(
    seeds_yaml_path: str = "seeds.yaml",
    graders_yaml_path: str = "graders_consolidated.yaml"
) -> YamlLoader:
    """Create and return a configured YAML loader."""
    return YamlLoader(
        seeds_yaml_path=Path(seeds_yaml_path),
        graders_yaml_path=Path(graders_yaml_path)
    )

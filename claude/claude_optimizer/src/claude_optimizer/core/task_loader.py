"""Load and parse task type and runner configurations."""

from pathlib import Path
from typing import Any

import yaml

from claude_optimizer.core.models import (
    TaskSetup,
    DockerConfig,
    GitCloneConfig,
    FileBasedGrading,
    ComparisonGrading,
    MessageBasedGrading,
    TaskType,
    TaskDefinition,
    GradingConfig,
)


def parse_setup_config(config: dict[str, Any]) -> TaskSetup | None:
    """Parse setup configuration from YAML data.
    
    Returns a TaskSetup object or None if incomplete.
    Supports both old single-type format and new composite format.
    """
    # Handle new composite format
    if "docker" in config or "git_clone" in config:
        docker_cfg = None
        git_cfg = None
        
        if docker_data := config.get("docker"):
            docker_cfg = DockerConfig(
                image=docker_data["image"],
                volumes=docker_data.get("volumes", {}),
                env=docker_data.get("env", {}),
                network_enabled=docker_data.get("network_enabled", True)
            )
        
        if git_data := config.get("git_clone"):
            # Only create if we have complete data
            if git_data.get("repo") and git_data.get("commit"):
                git_cfg = GitCloneConfig(
                    repo=git_data["repo"],
                    commit=git_data["commit"],
                    subdir=git_data.get("subdir")
                )
        
        if docker_cfg or git_cfg:
            return TaskSetup(docker=docker_cfg, git_clone=git_cfg)
        else:
            return None  # Incomplete setup
    
    # Handle old single-type format for backwards compatibility
    setup_type = config.get("type")
    if not setup_type:
        return None
        
    if setup_type == "docker":
        docker_cfg = DockerConfig(
            image=config["image"],
            volumes=config.get("volumes", {}),
            env=config.get("env", {}),
            network_enabled=config.get("network_enabled", True)
        )
        return TaskSetup(docker=docker_cfg, git_clone=None)
        
    elif setup_type == "git_clone":
        # Only create if we have complete data
        if config.get("repo") and config.get("commit"):
            git_cfg = GitCloneConfig(
                repo=config["repo"],
                commit=config["commit"],
                subdir=config.get("subdir")
            )
            return TaskSetup(docker=None, git_clone=git_cfg)
        else:
            return None  # Incomplete setup
            
    elif setup_type == "none":
        return None
        
    else:
        raise ValueError(f"Unknown setup type: {setup_type}")


def parse_grading_config(config: dict[str, Any]) -> GradingConfig | None:
    """Parse grading configuration from YAML data."""
    if not config:
        return None
        
    strategy = config.get("strategy")
    if not strategy:
        return None
    
    if strategy == "file_based":
        return FileBasedGrading(
            criteria_file=config.get("criteria_file"),
            criteria=config.get("criteria")
        )
    elif strategy == "message_based":
        return MessageBasedGrading(
            criteria_file=config.get("criteria_file"),
            criteria=config.get("criteria")
        )
    elif strategy == "comparison":
        # For comparison, we may not have reference at task type level
        reference = config.get("reference", "")
        if reference:
            return ComparisonGrading(
                reference=reference,
                criteria=config.get("criteria", [])
            )
        else:
            return None  # Incomplete - will be filled by tasks
    else:
        raise ValueError(f"Unknown grading strategy: {strategy}")


def load_task_types(file_path: Path | str) -> dict[str, TaskType]:
    """Load task type definitions from YAML file.
    
    Args:
        file_path: Path to task_types.yaml
        
    Returns:
        Dictionary mapping task type names to TaskType objects
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Task types file not found: {file_path}")
    
    with open(file_path) as f:
        data = yaml.safe_load(f)
    
    task_types = {}
    for name, config in data["task_types"].items():
        # Handle None setup/grading configs
        setup_config = config.get("setup")
        grading_config = config.get("grading")
        
        setup = parse_setup_config(setup_config) if setup_config else None
        grading = parse_grading_config(grading_config) if grading_config else None
        
        task_types[name] = TaskType(
            name=name,
            setup=setup,
            grading=grading
        )
    
    return task_types


def load_runner_configs(file_path: Path | str) -> dict[str, dict[str, Any]]:
    """Load runner configurations from YAML file.
    
    Args:
        file_path: Path to runners.yaml
        
    Returns:
        Dictionary mapping runner names to their configurations
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Runners file not found: {file_path}")
    
    with open(file_path) as f:
        data = yaml.safe_load(f)
    
    return data["runners"]


def load_task_definitions(
    file_path: Path | str,
    task_types: dict[str, TaskType] | None = None
) -> list[TaskDefinition]:
    """Load task definitions from seeds YAML file.
    
    Args:
        file_path: Path to seeds.yaml
        task_types: Optional task types for validation
        
    Returns:
        List of TaskDefinition objects
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Seeds file not found: {file_path}")
    
    with open(file_path) as f:
        data = yaml.safe_load(f)
    
    tasks = []
    for task_data in data.get("tasks", []):
        # Parse setup overrides if present
        setup_overrides = None
        if "setup_overrides" in task_data:
            setup_overrides = parse_setup_config(task_data["setup_overrides"])
        
        # Parse grading overrides if present
        grading_overrides = None
        if "grading_overrides" in task_data:
            grading_overrides = parse_grading_config(task_data["grading_overrides"])
        
        task = TaskDefinition(
            id=task_data["id"],
            prompt=task_data["prompt"],
            type=task_data.get("type", "coding"),  # Default to coding
            setup_overrides=setup_overrides,
            grading_overrides=grading_overrides,
            description=task_data.get("description"),
            allowed_tools=task_data.get("allowed_tools"),
            pre_task_commands=task_data.get("pre_task_commands")
        )
        
        # Validate task type if provided
        if task_types and task.type not in task_types:
            raise ValueError(f"Task {task.id} has unknown type: {task.type}")
        
        tasks.append(task)
    
    return tasks
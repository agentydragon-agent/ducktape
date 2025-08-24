"""Load and parse task type and runner configurations."""

from pathlib import Path
from typing import Any

import yaml

from claude_optimizer.core.models import (
    DockerSetup,
    GitCloneSetup,
    NoSetup,
    FileBasedGrading,
    ComparisonGrading,
    MessageBasedGrading,
    TaskType,
    TaskDefinition,
    SetupConfig,
    GradingConfig,
)


def parse_setup_config(config: dict[str, Any]) -> SetupConfig:
    """Parse setup configuration from YAML data."""
    setup_type = config.get("type", "none")
    
    if setup_type == "docker":
        return DockerSetup(
            image=config["image"],
            volumes=config.get("volumes", {}),
            env=config.get("env", {})
        )
    elif setup_type == "git_clone":
        return GitCloneSetup(
            repo=config.get("repo", ""),  # May be specified per task
            commit=config.get("commit", ""),
            subdir=config.get("subdir")
        )
    elif setup_type == "none":
        return NoSetup()
    else:
        raise ValueError(f"Unknown setup type: {setup_type}")


def parse_grading_config(config: dict[str, Any]) -> GradingConfig:
    """Parse grading configuration from YAML data."""
    strategy = config["strategy"]
    
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
        return ComparisonGrading(
            reference=config.get("reference", ""),  # May be specified per task
            criteria=config.get("criteria", [])
        )
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
        setup = parse_setup_config(config["setup"])
        grading = parse_grading_config(config["grading"])
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
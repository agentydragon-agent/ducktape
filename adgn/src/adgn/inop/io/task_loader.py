"""Load and parse task type and runner configurations."""

from pathlib import Path
from typing import Any

from pydantic import TypeAdapter
import yaml

from adgn.inop.engine.models import GradingConfig, TaskDefinition, TaskSetup, TaskTypeConfig, TaskTypeName


def load_task_types(file_path: Path | str) -> dict[str, TaskTypeConfig]:
    """Load task type definitions from YAML file.

    Args:
        file_path: Path to task_types.yaml

    Returns:
        Dictionary mapping task type names to TaskTypeConfig objects
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Task types file not found: {file_path}")

    with file_path.open() as f:
        data = yaml.safe_load(f)

    task_types = {}
    for name, config in data["task_types"].items():
        # Only grading config for task types (setup is per-task)
        grading = (
            TypeAdapter(GradingConfig).validate_python(config["grading"]) if config.get("grading") else None
        )
        task_types[name] = TaskTypeConfig(name=TaskTypeName(name), grading=grading)

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

    with file_path.open() as f:
        data = yaml.safe_load(f)

    runners = data.get("runners") or {}
    # Validate and coerce to precise type to avoid Any leakage
    return TypeAdapter(dict[str, dict[str, Any]]).validate_python(runners)


def load_task_definitions(
    file_path: Path | str, task_types: dict[str, TaskTypeConfig] | None = None
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

    with file_path.open() as f:
        data = yaml.safe_load(f)

    tasks = []
    for task_data in data.get("tasks", []):
        # Parse setup and grading overrides if present
        setup_overrides = (
            TaskSetup.model_validate(task_data["setup_overrides"]) if "setup_overrides" in task_data else None
        )
        grading_overrides = (
            TypeAdapter(GradingConfig).validate_python(task_data["grading_overrides"])
            if "grading_overrides" in task_data
            else None
        )

        task = TaskDefinition(
            id=task_data["id"],
            prompt=task_data["prompt"],
            type=task_data.get("type", "coding"),  # Default to coding
            setup_overrides=setup_overrides,
            grading_overrides=grading_overrides,
            description=task_data.get("description"),
            allowed_tools=task_data.get("allowed_tools"),
            pre_task_commands=task_data.get("pre_task_commands"),
        )

        # Validate task type if provided
        if task_types and task.type not in task_types:
            raise ValueError(f"Task {task.id} has unknown type: {task.type}")

        tasks.append(task)

    return tasks

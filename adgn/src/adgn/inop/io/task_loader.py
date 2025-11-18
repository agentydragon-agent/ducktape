"""Load and parse task type and runner configurations."""

from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError
import yaml

from adgn.inop.engine.models import GradingConfig, TaskDefinition, TaskSetup, TaskTypeConfig, TaskTypeName


def parse_setup_config(config: dict[str, Any]) -> TaskSetup | None:
    """Parse setup configuration from YAML data.

    Returns a TaskSetup object or None if config is empty/None.
    Git clone, Docker, and sandbox are orthogonal concerns that can be combined.
    """
    if not config:
        return None

    return TypeAdapter(TaskSetup).validate_python(config)


def parse_grading_config(config: dict[str, Any]) -> GradingConfig | None:
    """Parse grading configuration from YAML data.

    Returns None if config is empty, strategy is missing, or for incomplete
    comparison grading (missing reference at task type level).
    """
    if not config:
        return None

    strategy = config.get("strategy")
    if not strategy:
        return None

    try:
        return TypeAdapter(GradingConfig).validate_python(config)
    except ValidationError:
        # For comparison strategy, reference may be incomplete at task type level
        # and filled in by individual tasks
        if strategy == "comparison" and not config.get("reference"):
            return None  # Incomplete - will be filled by tasks
        raise


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
        grading_config = config.get("grading")
        grading = parse_grading_config(grading_config) if grading_config else None

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
            pre_task_commands=task_data.get("pre_task_commands"),
        )

        # Validate task type if provided
        if task_types and task.type not in task_types:
            raise ValueError(f"Task {task.id} has unknown type: {task.type}")

        tasks.append(task)

    return tasks

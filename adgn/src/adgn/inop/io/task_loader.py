"""Load and parse task type and runner configurations."""

from pathlib import Path
from typing import Any

from pydantic import TypeAdapter
import yaml

from adgn.inop.engine.models import TaskDefinition, TaskDefinitionsYaml, TaskTypeConfig, TaskTypeName, TaskTypesYaml


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
        config = TaskTypesYaml.model_validate(yaml.safe_load(f))

    return {name: TaskTypeConfig(name=TaskTypeName(name), grading=cfg.grading) for name, cfg in config.task_types.items()}


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
        config = TaskDefinitionsYaml.model_validate(
            yaml.safe_load(f), context={"task_types": task_types} if task_types else None
        )

    return config.tasks

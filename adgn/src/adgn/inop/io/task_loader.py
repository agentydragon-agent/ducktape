"""Load and parse task type and runner configurations."""

from pathlib import Path
from typing import Any

from pydantic import TypeAdapter
import yaml

from adgn.inop.engine.models import (
    ComparisonGrading,
    DockerConfig,
    FileBasedGrading,
    GitCloneConfig,
    GradingConfig,
    MessageBasedGrading,
    SandboxConfig,
    TaskDefinition,
    TaskSetup,
    TaskType,
)


def parse_setup_config(config: dict[str, Any]) -> TaskSetup | None:
    """Parse setup configuration from YAML data.

    Returns a TaskSetup object or None if config is empty/None.
    Git clone, Docker, and sandbox are orthogonal concerns that can be combined.
    """
    if not config:
        return None

    docker_cfg = None
    git_cfg = None
    sandbox_cfg = None

    if docker_data := config.get("docker"):
        docker_cfg = DockerConfig(
            image=docker_data["image"],
            volumes=docker_data.get("volumes", {}),
            env=docker_data.get("env", {}),
            network_enabled=docker_data.get("network_enabled", True),
        )

    if (
        (git_data := config.get("git_clone"))
        and git_data.get("repo")
        and git_data.get("commit")
    ):
        git_cfg = GitCloneConfig(
            repo=git_data["repo"],
            commit=git_data["commit"],
            subdir=git_data.get("subdir"),
        )

    if sandbox_data := config.get("sandbox"):
        sandbox_cfg = SandboxConfig(
            enabled=sandbox_data.get("enabled", True),
            read_only_paths=sandbox_data.get("read_only_paths", []),
            read_write_paths=sandbox_data.get("read_write_paths", []),
            allow_network=sandbox_data.get("allow_network", False),
            bind_system=sandbox_data.get("bind_system", True),
        )

    # Return TaskSetup with whatever is configured (all are optional)
    return TaskSetup(git_clone=git_cfg, docker=docker_cfg, sandbox=sandbox_cfg)


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
            criteria=config.get("criteria"),
        )
    if strategy == "message_based":
        return MessageBasedGrading(
            criteria_file=config.get("criteria_file"),
            criteria=config.get("criteria"),
        )
    if strategy == "comparison":
        # For comparison, we may not have reference at task type level
        reference = config.get("reference", "")
        if reference:
            return ComparisonGrading(
                reference=reference,
                criteria=config.get("criteria", []),
            )
        return None  # Incomplete - will be filled by tasks
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

    with file_path.open() as f:
        data = yaml.safe_load(f)

    task_types = {}
    for name, config in data["task_types"].items():
        # Only grading config for task types (setup is per-task)
        grading_config = config.get("grading")
        grading = parse_grading_config(grading_config) if grading_config else None

        task_types[name] = TaskType(
            name=name,
            grading=grading,
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

    with file_path.open() as f:
        data = yaml.safe_load(f)

    runners = data.get("runners") or {}
    # Validate and coerce to precise type to avoid Any leakage
    return TypeAdapter(dict[str, dict[str, Any]]).validate_python(runners)


def load_task_definitions(
    file_path: Path | str,
    task_types: dict[str, TaskType] | None = None,
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

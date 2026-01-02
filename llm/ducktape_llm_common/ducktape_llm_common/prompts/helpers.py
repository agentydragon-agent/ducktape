"""Helper functions for loading and working with specific prompts."""

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import PromptName
from .loader import PromptVariableError, load_prompt


def load_work_tracking_prompt(
    agent_name: str, task_id: str, project_name: str, context: str | None = None, **extra_vars
) -> str:
    """Load the work tracking prompt with standard variables."""
    variables = {
        "agent_name": agent_name,
        "task_id": task_id,
        "project_name": project_name,
        "timestamp": datetime.now().isoformat(),
        "context": context or "No additional context provided",
        **extra_vars,
    }

    return load_prompt(PromptName.WORK_TRACKING, variables)


def load_task_management_prompt(
    task_id: str, goal: str, deliverables: list[str], constraints: list[str] | None = None, **extra_vars
) -> str:
    """Load the task management prompt with required information."""
    variables = {
        "task_id": task_id,
        "goal": goal,
        "deliverables": "\n".join(f"- {d}" for d in deliverables),
        "constraints": "\n".join(f"- {c}" for c in (constraints or ["None"])),
        "timestamp": datetime.now().isoformat(),
        **extra_vars,
    }

    return load_prompt(PromptName.TASK_MANAGEMENT, variables)


def load_debugging_protocol_prompt(
    error_description: str,
    context: str,
    stack_trace: str | None = None,
    attempted_solutions: list[str] | None = None,
    **extra_vars,
) -> str:
    """Load the debugging protocol prompt."""
    variables = {
        "error_description": error_description,
        "context": context,
        "stack_trace": stack_trace or "No stack trace available",
        "attempted_solutions": "\n".join(f"- {s}" for s in (attempted_solutions or ["None"])),
        "timestamp": datetime.now().isoformat(),
        **extra_vars,
    }

    return load_prompt(PromptName.DEBUGGING_PROTOCOL, variables)


def load_spawn_coordination_prompt(
    team_id: str, agents: list[str], task_graph: str, coordination_strategy: str | None = None, **extra_vars
) -> str:
    """Load the spawn coordination prompt for multi-agent teams."""
    variables = {
        "team_id": team_id,
        "agents": "\n".join(f"- {agent}" for agent in agents),
        "task_graph": task_graph,
        "coordination_strategy": coordination_strategy or "Default coordination",
        "timestamp": datetime.now().isoformat(),
        **extra_vars,
    }

    return load_prompt(PromptName.SPAWN_COORDINATION, variables)


def load_investigation_setup_prompt(
    investigation_id: str,
    title: str,
    goal: str,
    initial_evidence: list[str] | None = None,
    methodology: str | None = None,
    **extra_vars,
) -> str:
    """Load the investigation setup prompt."""
    variables = {
        "investigation_id": investigation_id,
        "title": title,
        "goal": goal,
        "initial_evidence": "\n".join(f"- {e}" for e in (initial_evidence or ["None"])),
        "methodology": methodology or "Standard investigation methodology",
        "timestamp": datetime.now().isoformat(),
        **extra_vars,
    }

    return load_prompt(PromptName.INVESTIGATION_SETUP, variables)


def load_metadata_validation_prompt(
    file_path: str, expected_version: int, validation_rules: list[str] | None = None, **extra_vars
) -> str:
    """Load the metadata validation prompt."""
    variables = {
        "file_path": file_path,
        "expected_version": str(expected_version),
        "validation_rules": "\n".join(f"- {r}" for r in (validation_rules or ["Standard validation rules"])),
        "timestamp": datetime.now().isoformat(),
        **extra_vars,
    }

    return load_prompt(PromptName.METADATA_VALIDATION, variables)


def create_prompt_with_defaults(
    prompt_name: PromptName, required_vars: dict[str, Any], optional_vars: dict[str, Any] | None = None
) -> str:
    """Raises PromptVariableError if required variables are missing."""
    # Set up default values for common variables
    defaults = {
        "timestamp": datetime.now().isoformat(),
        "working_directory": str(Path.cwd()),
        "user_name": "User",
        "agent_name": "AI Assistant",
    }

    # Merge variables with defaults
    variables = {
        **defaults,
        **(optional_vars or {}),
        **required_vars,  # Required vars override everything
    }

    return load_prompt(prompt_name.value, variables)


def validate_prompt_variables(prompt_name: PromptName, provided_vars: dict[str, Any]) -> tuple[bool, list[str]]:
    """Returns (is_valid, list_of_missing_variables)."""
    # Try to load the prompt with the provided variables
    try:
        load_prompt(prompt_name.value, provided_vars, allow_missing_vars=False)
        return True, []
    except PromptVariableError as e:
        # Extract missing variable from error message
        error_msg = str(e)
        if "Missing required variable" in error_msg:
            # Parse the variable name from the error
            match = re.search(r"'(\w+)'", error_msg)
            if match:
                return False, [match.group(1)]
        return False, ["Unknown variable"]
    except (AttributeError, KeyError, TypeError):
        # Other errors aren't about missing variables
        return True, []


def get_prompt_variables(prompt_name: PromptName) -> list[str]:
    """Extract all variables used in a prompt."""
    try:
        # Load the raw prompt without substitution
        content = load_prompt(prompt_name.value, use_cache=False)
    except (FileNotFoundError, OSError):
        return []

    # Extract variables using regex
    # Find {variable} style
    format_vars = re.findall(r"\{(\w+)\}", content)

    # Find $variable and ${variable} style
    template_vars = re.findall(r"\$\{?(\w+)\}?", content)

    # Combine and deduplicate
    all_vars = list(set(format_vars + template_vars))

    return sorted(all_vars)

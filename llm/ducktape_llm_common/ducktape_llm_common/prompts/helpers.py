"""Helper functions for loading and working with specific prompts."""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .constants import PromptName
from .loader import PromptVariableError, load_prompt


def load_work_tracking_prompt(
    agent_name: str,
    task_id: str,
    project_name: str,
    context: Optional[str] = None,
    **extra_vars,
) -> str:
    """Load the work tracking prompt with standard variables.

    Args:
        agent_name: Name of the AI agent
        task_id: Unique task identifier
        project_name: Name of the project
        context: Optional additional context
        **extra_vars: Any additional variables for the prompt

    Returns:
        The formatted work tracking prompt
    """
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
    task_id: str,
    goal: str,
    deliverables: list[str],
    constraints: Optional[list[str]] = None,
    **extra_vars,
) -> str:
    """Load the task management prompt with required information.

    Args:
        task_id: Unique task identifier
        goal: The goal to achieve
        deliverables: List of expected deliverables
        constraints: Optional list of constraints
        **extra_vars: Any additional variables

    Returns:
        The formatted task management prompt
    """
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
    stack_trace: Optional[str] = None,
    attempted_solutions: Optional[list[str]] = None,
    **extra_vars,
) -> str:
    """Load the debugging protocol prompt.

    Args:
        error_description: Description of the error
        context: Context in which the error occurred
        stack_trace: Optional stack trace
        attempted_solutions: Optional list of already attempted solutions
        **extra_vars: Any additional variables

    Returns:
        The formatted debugging protocol prompt
    """
    variables = {
        "error_description": error_description,
        "context": context,
        "stack_trace": stack_trace or "No stack trace available",
        "attempted_solutions": "\n".join(
            f"- {s}" for s in (attempted_solutions or ["None"])
        ),
        "timestamp": datetime.now().isoformat(),
        **extra_vars,
    }

    return load_prompt(PromptName.DEBUGGING_PROTOCOL, variables)


def load_spawn_coordination_prompt(
    team_id: str,
    agents: list[str],
    task_graph: str,
    coordination_strategy: Optional[str] = None,
    **extra_vars,
) -> str:
    """Load the spawn coordination prompt for multi-agent teams.

    Args:
        team_id: Unique team identifier
        agents: List of agent names
        task_graph: Task dependency graph description
        coordination_strategy: Optional coordination strategy
        **extra_vars: Any additional variables

    Returns:
        The formatted spawn coordination prompt
    """
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
    initial_evidence: Optional[list[str]] = None,
    methodology: Optional[str] = None,
    **extra_vars,
) -> str:
    """Load the investigation setup prompt.

    Args:
        investigation_id: Unique investigation identifier
        title: Investigation title
        goal: What the investigation aims to discover
        initial_evidence: Optional list of initial evidence
        methodology: Optional investigation methodology
        **extra_vars: Any additional variables

    Returns:
        The formatted investigation setup prompt
    """
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
    file_path: str,
    expected_version: int,
    validation_rules: Optional[list[str]] = None,
    **extra_vars,
) -> str:
    """Load the metadata validation prompt.

    Args:
        file_path: Path to the file to validate
        expected_version: Expected metadata version
        validation_rules: Optional list of validation rules
        **extra_vars: Any additional variables

    Returns:
        The formatted metadata validation prompt
    """
    variables = {
        "file_path": file_path,
        "expected_version": str(expected_version),
        "validation_rules": "\n".join(
            f"- {r}" for r in (validation_rules or ["Standard validation rules"])
        ),
        "timestamp": datetime.now().isoformat(),
        **extra_vars,
    }

    return load_prompt(PromptName.METADATA_VALIDATION, variables)


def create_prompt_with_defaults(
    prompt_name: PromptName,
    required_vars: Dict[str, Any],
    optional_vars: Optional[Dict[str, Any]] = None,
) -> str:
    """Create a prompt with default values for common variables.

    Args:
        prompt_name: Name of the prompt to load
        required_vars: Required variables that must be provided
        optional_vars: Optional variables with defaults

    Returns:
        The formatted prompt

    Raises:
        PromptVariableError: If required variables are missing
    """
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


def validate_prompt_variables(
    prompt_name: PromptName, provided_vars: Dict[str, Any]
) -> tuple[bool, list[str]]:
    """Validate that all required variables are provided for a prompt.

    Args:
        prompt_name: Name of the prompt
        provided_vars: Variables that will be provided

    Returns:
        Tuple of (is_valid, list_of_missing_variables)
    """
    # Try to load the prompt with the provided variables
    try:
        load_prompt(prompt_name.value, provided_vars, allow_missing_vars=False)
        return True, []
    except PromptVariableError as e:
        # Extract missing variable from error message
        error_msg = str(e)
        if "Missing required variable" in error_msg:
            # Parse the variable name from the error
            import re

            match = re.search(r"'(\w+)'", error_msg)
            if match:
                return False, [match.group(1)]
        return False, ["Unknown variable"]
    except Exception:
        # Other errors aren't about missing variables
        return True, []


def get_prompt_variables(prompt_name: PromptName) -> list[str]:
    """Extract all variables used in a prompt.

    Args:
        prompt_name: Name of the prompt

    Returns:
        List of variable names found in the prompt
    """
    try:
        # Load the raw prompt without substitution
        content = load_prompt(prompt_name.value, use_cache=False)
    except Exception:
        return []

    # Extract variables using regex
    import re

    # Find {variable} style
    format_vars = re.findall(r"\{(\w+)\}", content)

    # Find $variable and ${variable} style
    template_vars = re.findall(r"\$\{?(\w+)\}?", content)

    # Combine and deduplicate
    all_vars = list(set(format_vars + template_vars))

    return sorted(all_vars)

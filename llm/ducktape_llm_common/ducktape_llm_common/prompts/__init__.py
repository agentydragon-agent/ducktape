"""Prompts and instructions for AI agents.

This module provides a comprehensive system for loading, managing, and validating
prompts that guide AI agents through standard workflows and procedures.

Features:
- Prompt discovery across multiple directories
- Variable substitution with multiple template formats
- Validation for prompt structure and content
- Helper functions for common prompts
- Metadata extraction and management
"""

# Import all components
from .constants import COMMON_VARIABLES, PromptName
from .helpers import (
    create_prompt_with_defaults,
    get_prompt_variables,
    load_debugging_protocol_prompt,
    load_investigation_setup_prompt,
    load_metadata_validation_prompt,
    load_spawn_coordination_prompt,
    load_task_management_prompt,
    load_work_tracking_prompt,
    validate_prompt_variables,
)
from .loader import (
    PromptError,
    PromptLoader,
    PromptNotFoundError,
    PromptValidationError,
    PromptVariableError,
    clear_prompt_cache,
    discover_prompts,
    get_prompt_metadata,
    list_prompts,
    load_prompt,
    validate_prompt,
)
from .validation import PromptValidator, validate_prompt_collection, validate_prompt_file

# Maintain backward compatibility with original simple interface
get_prompt = load_prompt
list_available_prompts = list_prompts

# Legacy constants for backward compatibility
WORK_TRACKING_PROMPT = PromptName.WORK_TRACKING.value
EVIDENCE_GATHERING_PROMPT = PromptName.EVIDENCE_GATHERING.value
TASK_MANAGEMENT_PROMPT = PromptName.TASK_MANAGEMENT.value
DEBUGGING_PROTOCOL_PROMPT = PromptName.DEBUGGING_PROTOCOL.value

__all__ = [
    "COMMON_VARIABLES",
    "DEBUGGING_PROTOCOL_PROMPT",
    "EVIDENCE_GATHERING_PROMPT",
    "TASK_MANAGEMENT_PROMPT",
    "WORK_TRACKING_PROMPT",
    # Exceptions
    "PromptError",
    # Core functionality
    "PromptLoader",
    # Constants and enums
    "PromptName",
    "PromptNotFoundError",
    "PromptValidationError",
    # Validation
    "PromptValidator",
    "PromptVariableError",
    "clear_prompt_cache",
    "create_prompt_with_defaults",
    "discover_prompts",
    # Backward compatibility
    "get_prompt",
    "get_prompt_metadata",
    "get_prompt_variables",
    "list_available_prompts",
    "list_prompts",
    "load_debugging_protocol_prompt",
    "load_investigation_setup_prompt",
    "load_metadata_validation_prompt",
    "load_prompt",
    "load_spawn_coordination_prompt",
    "load_task_management_prompt",
    # Helper functions
    "load_work_tracking_prompt",
    "validate_prompt",
    "validate_prompt_collection",
    "validate_prompt_file",
    "validate_prompt_variables",
]

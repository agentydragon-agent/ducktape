"""Constants and enumerations for the prompt system."""

from enum import Enum


class PromptName(str, Enum):
    """Standard prompt names used across the system.

    Using string enum for easy serialization and comparison.
    """

    # Work tracking and evidence
    WORK_TRACKING = "work_tracking"
    EVIDENCE_GATHERING = "evidence_gathering"

    # Task management
    TASK_MANAGEMENT = "task_management"
    TASK_BREAKDOWN = "task_breakdown"
    TASK_PRIORITIZATION = "task_prioritization"

    # Development workflows
    DEBUGGING_PROTOCOL = "debugging_protocol"
    CODE_REVIEW = "code_review"
    REFACTORING_GUIDE = "refactoring_guide"

    # Team coordination
    SPAWN_COORDINATION = "spawn_coordination"
    TEAM_HANDOFF = "team_handoff"
    STATUS_REPORTING = "status_reporting"

    # Investigation and analysis
    INVESTIGATION_SETUP = "investigation_setup"
    ROOT_CAUSE_ANALYSIS = "root_cause_analysis"
    ARCHITECTURE_REVIEW = "architecture_review"

    # Validation and quality
    METADATA_VALIDATION = "metadata_validation"
    URL_CHECKING = "url_checking"
    DOCUMENTATION_REVIEW = "documentation_review"

    # AI-specific workflows
    PROMPT_ENGINEERING = "prompt_engineering"
    MODEL_EVALUATION = "model_evaluation"
    CONTEXT_MANAGEMENT = "context_management"

    @classmethod
    def get_description(cls, prompt_name: "PromptName") -> str:
        """Get a human-readable description of a prompt.

        Args:
            prompt_name: The prompt to describe

        Returns:
            Description of the prompt's purpose
        """
        descriptions = {
            cls.WORK_TRACKING: "Track work progress with evidence and context",
            cls.EVIDENCE_GATHERING: "Collect and organize evidence for claims",
            cls.TASK_MANAGEMENT: "Manage tasks with clear goals and deliverables",
            cls.TASK_BREAKDOWN: "Break down complex tasks into manageable steps",
            cls.TASK_PRIORITIZATION: "Prioritize tasks based on impact and dependencies",
            cls.DEBUGGING_PROTOCOL: "Systematic approach to debugging issues",
            cls.CODE_REVIEW: "Review code for quality, security, and best practices",
            cls.REFACTORING_GUIDE: "Guide for safe and effective code refactoring",
            cls.SPAWN_COORDINATION: "Coordinate multi-agent team workflows",
            cls.TEAM_HANDOFF: "Hand off work between team members effectively",
            cls.STATUS_REPORTING: "Report status with clarity and actionable information",
            cls.INVESTIGATION_SETUP: "Set up structured investigations",
            cls.ROOT_CAUSE_ANALYSIS: "Analyze root causes of issues systematically",
            cls.ARCHITECTURE_REVIEW: "Review system architecture and design decisions",
            cls.METADATA_VALIDATION: "Validate metadata structure and content",
            cls.URL_CHECKING: "Check and validate URLs in documentation",
            cls.DOCUMENTATION_REVIEW: "Review documentation for completeness and clarity",
            cls.PROMPT_ENGINEERING: "Engineer effective prompts for AI systems",
            cls.MODEL_EVALUATION: "Evaluate model performance and behavior",
            cls.CONTEXT_MANAGEMENT: "Manage context windows and information flow",
        }
        return descriptions.get(prompt_name, "No description available")

    @classmethod
    def get_category(cls, prompt_name: "PromptName") -> str:
        """Get the category of a prompt.

        Args:
            prompt_name: The prompt to categorize

        Returns:
            Category name
        """
        categories = {
            # Work tracking
            cls.WORK_TRACKING: "Work Management",
            cls.EVIDENCE_GATHERING: "Work Management",
            # Task management
            cls.TASK_MANAGEMENT: "Task Management",
            cls.TASK_BREAKDOWN: "Task Management",
            cls.TASK_PRIORITIZATION: "Task Management",
            # Development
            cls.DEBUGGING_PROTOCOL: "Development",
            cls.CODE_REVIEW: "Development",
            cls.REFACTORING_GUIDE: "Development",
            # Team coordination
            cls.SPAWN_COORDINATION: "Team Coordination",
            cls.TEAM_HANDOFF: "Team Coordination",
            cls.STATUS_REPORTING: "Team Coordination",
            # Investigation
            cls.INVESTIGATION_SETUP: "Investigation",
            cls.ROOT_CAUSE_ANALYSIS: "Investigation",
            cls.ARCHITECTURE_REVIEW: "Investigation",
            # Validation
            cls.METADATA_VALIDATION: "Validation",
            cls.URL_CHECKING: "Validation",
            cls.DOCUMENTATION_REVIEW: "Validation",
            # AI workflows
            cls.PROMPT_ENGINEERING: "AI Workflows",
            cls.MODEL_EVALUATION: "AI Workflows",
            cls.CONTEXT_MANAGEMENT: "AI Workflows",
        }
        return categories.get(prompt_name, "Uncategorized")

    @classmethod
    def by_category(cls) -> dict[str, list["PromptName"]]:
        """Get all prompts organized by category.

        Returns:
            Dictionary mapping category names to lists of prompts
        """
        result: dict[str, list[PromptName]] = {}

        for prompt in cls:
            category = cls.get_category(prompt)
            if category not in result:
                result[category] = []
            result[category].append(prompt)

        # Sort prompts within each category
        for prompts in result.values():
            prompts.sort(key=lambda x: x.value)

        return result


# Prompt template variable definitions
COMMON_VARIABLES = {
    "agent_name": "Name of the AI agent",
    "task_id": "Unique identifier for the task",
    "project_name": "Name of the project",
    "working_directory": "Current working directory path",
    "timestamp": "Current timestamp",
    "user_name": "Name of the user",
    "context": "Additional context information",
    "goal": "The goal to achieve",
    "constraints": "Any constraints or limitations",
    "deliverables": "Expected deliverables",
}


# Prompt file naming conventions
PROMPT_FILE_EXTENSION = ".md"
PROMPT_METADATA_SUFFIX = ".meta.yaml"
PROMPT_EXAMPLE_SUFFIX = ".example.md"
PROMPT_TEST_SUFFIX = ".test.yaml"

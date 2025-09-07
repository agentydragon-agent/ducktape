"""Grading strategy implementations."""

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from adgn_llm.instruction_optimizer.config import OptimizerConfig
from adgn_llm.instruction_optimizer.engine.models import (
    AssistantMessage,
    ComparisonGrading,
    Criterion,
    FileBasedGrading,
    FinalOutput,
    GradingConfig,
    GradingContext,
    MessageBasedGrading,
    TaskDefinition,
    ToolCall,
    TrajectoryItem,
)
from adgn_llm.instruction_optimizer.io.yaml_loader import load_yaml_files
from adgn_llm.instruction_optimizer.prompting.truncation_utils import TruncationManager


class GradingStrategy(ABC):
    """Base class for grading strategies."""

    @abstractmethod
    def collect_artifacts(self, context: GradingContext) -> dict[str, Any]:
        """Collect artifacts to be graded from the rollout and environment.

        Args:
            context: Grading context with rollout, task, and environment

        Returns:
            Dictionary of artifacts to grade
        """

    @abstractmethod
    def prepare_for_grader(
        self,
        artifacts: dict[str, Any],
        config: OptimizerConfig,
    ) -> dict[str, Any]:
        """Prepare artifacts for the grading model.

        Args:
            artifacts: Raw artifacts from collect_artifacts
            config: Optimizer configuration for truncation settings

        Returns:
            Dictionary ready for grading model
        """

    @abstractmethod
    def get_grading_prompt(
        self,
        prepared_artifacts: dict[str, Any],
        task: TaskDefinition,
    ) -> str:
        """Generate the grading prompt for this strategy.

        Args:
            prepared_artifacts: Artifacts prepared by prepare_for_grader
            task: Task being graded

        Returns:
            Prompt string for the grader
        """


class FileBasedGradingStrategy(GradingStrategy):
    """Grade based on files produced by the agent."""

    def __init__(self, criteria: list[Criterion] | None = None):
        self.criteria = criteria or []

    def collect_artifacts(self, context: GradingContext) -> dict[str, Any]:
        """Collect files from environment or rollout."""
        files = {}

        # Try to get files from environment first (container/workspace)
        if context.environment:
            if context.environment.type == "docker_container":
                # TODO: Implement container file collection
                # container_id = context.environment.container_id
                # files = collect_from_container(container_id)
                pass
            elif context.environment.type == "workspace_dir":
                # Collect files from workspace directory
                workspace = context.environment.workspace_path
                if workspace and Path(workspace).exists():
                    files = self._collect_from_directory(workspace)

        # Fall back to files in rollout
        if not files and context.rollout.files:
            files = context.rollout.files

        # Last resort: try to extract from trajectory
        if not files:
            files = self._extract_files_from_trajectory(context.rollout.trajectory)

        return {"files": files}

    def _collect_from_directory(self, directory: str) -> dict[str, str]:
        """Collect all files from a directory."""
        files = {}
        directory_path = Path(directory)
        for root, _, filenames in os.walk(directory):
            for filename in filenames:
                filepath = Path(root) / filename
                relative_path = filepath.relative_to(directory_path).as_posix()
                try:
                    files[relative_path] = filepath.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    # Skip binary or unreadable files
                    continue
        return files

    def _extract_files_from_trajectory(
        self,
        trajectory: list[TrajectoryItem],
    ) -> dict[str, str]:
        """Extract files from Write/Edit tool calls in trajectory."""
        files = {}
        for item in trajectory:
            if isinstance(item, ToolCall) and item.tool_name in (
                "Write",
                "Edit",
                "MultiEdit",
            ):
                # Extract file content from tool call
                args = item.arguments
                if "file_path" in args:
                    path = args["file_path"]
                    if item.tool_name == "Write":
                        content = args.get("content", "")
                    elif item.tool_name == "Edit":
                        content = args.get("new_string", "")
                    else:
                        content = ""  # MultiEdit is more complex
                    files[path] = content
        return files

    def prepare_for_grader(
        self,
        artifacts: dict[str, Any],
        config: OptimizerConfig,
    ) -> dict[str, Any]:
        """Truncate files for grading."""
        files = artifacts.get("files", {})
        t_mgr = TruncationManager(config)

        # Convert to list format for truncation
        file_list = [{"path": path, "content": content} for path, content in files.items()]

        # Truncate individual files
        truncated_files = []
        for file_info in file_list:
            truncated_content = t_mgr.truncate_text(
                file_info["content"],
                config.truncation.max_file_size_grading,
                "... [truncated for grading]",
            )
            truncated_files.append(
                {
                    "path": file_info["path"],
                    "content": truncated_content,
                },
            )

        # Further truncate by total token count
        truncated_files = t_mgr.truncate_files_by_tokens(
            truncated_files,
            config.tokens.max_files_tokens,
        )

        return {
            "type": "file_based",
            "files": truncated_files,
            "criteria": self.criteria,
        }

    def get_grading_prompt(
        self,
        prepared_artifacts: dict[str, Any],
        task: TaskDefinition,
    ) -> str:
        """Generate file-based grading prompt."""
        files = prepared_artifacts["files"]
        return f"Task: {task.prompt}\n\nFiles:\n{json.dumps(files, indent=2)}"


class MessageBasedGradingStrategy(GradingStrategy):
    """Grade based on final message output."""

    def __init__(self, criteria: list[Criterion] | None = None):
        self.criteria = criteria or []

    def collect_artifacts(self, context: GradingContext) -> dict[str, Any]:
        """Get final message from trajectory."""
        final_message = ""

        # Look for final output in trajectory
        for item in reversed(context.rollout.trajectory):
            if isinstance(item, FinalOutput):
                final_message = item.text
                break
            if isinstance(item, AssistantMessage):
                # Use last assistant message if no explicit final
                final_message = item.text

        # Fallback to rollout's final_output property
        if not final_message:
            final_message = context.rollout.final_output

        return {"final_message": final_message}

    def prepare_for_grader(
        self,
        artifacts: dict[str, Any],
        config: OptimizerConfig,
    ) -> dict[str, Any]:
        """Truncate message if needed."""
        message = artifacts.get("final_message", "")
        t_mgr = TruncationManager(config)

        # Truncate message to reasonable length
        truncated = t_mgr.truncate_text(
            message,
            config.truncation.max_file_size_grading * 2,  # Allow longer for messages
            "... [truncated]",
        )

        return {
            "type": "message_based",
            "message": truncated,
            "criteria": self.criteria,
        }

    def get_grading_prompt(
        self,
        prepared_artifacts: dict[str, Any],
        task: TaskDefinition,
    ) -> str:
        """Generate message-based grading prompt."""
        message = prepared_artifacts["message"]
        return f"Task: {task.prompt}\n\nAgent's Response:\n{message}"


class ComparisonGradingStrategy(GradingStrategy):
    """Grade by comparing output to reference."""

    def __init__(self, reference: str, criteria: list[dict[str, str]] | None = None):
        self.reference = reference
        self.criteria = criteria or []

    def collect_artifacts(self, context: GradingContext) -> dict[str, Any]:
        """Get agent output for comparison."""
        # Get final message - collect ALL assistant messages for code review
        # since the review might be spread across multiple messages
        all_messages = []
        final_message = ""

        for item in context.rollout.trajectory:
            if isinstance(item, AssistantMessage) and item.text:
                all_messages.append(item.text)
            elif isinstance(item, FinalOutput):
                final_message = item.text
                break

        # Use final output if present, otherwise concatenate all assistant messages
        if final_message:
            agent_output = final_message
        elif all_messages:
            agent_output = "\n\n".join(all_messages)
        else:
            agent_output = context.rollout.final_output

        return {
            "agent_output": agent_output,
            "reference": self.reference,
        }

    def prepare_for_grader(
        self,
        artifacts: dict[str, Any],
        config: OptimizerConfig,
    ) -> dict[str, Any]:
        """Prepare comparison artifacts."""
        t_mgr = TruncationManager(config)

        agent_output = t_mgr.truncate_text(
            artifacts.get("agent_output", ""),
            config.truncation.max_file_size_grading,
            "... [truncated]",
        )

        reference = t_mgr.truncate_text(
            artifacts.get("reference", ""),
            config.truncation.max_file_size_grading,
            "... [truncated]",
        )

        return {
            "type": "comparison",
            "agent_output": agent_output,
            "reference": reference,
            "criteria": self.criteria,
        }

    def get_grading_prompt(
        self,
        prepared_artifacts: dict[str, Any],
        task: TaskDefinition,
    ) -> str:
        """Generate comparison grading prompt."""
        agent_output = prepared_artifacts["agent_output"]
        reference = prepared_artifacts["reference"]
        criteria_desc = "\n".join(
            [f"- {c['name']}: {c['description']}" for c in prepared_artifacts["criteria"]],
        )

        return (
            f"Task: {task.prompt}\n\n"
            f"Agent's Output:\n{agent_output}\n\n"
            f"Reference Output:\n{reference}\n\n"
            f"Grading Criteria:\n{criteria_desc}\n\n"
            f"Compare the agent's output to the reference and grade based on the criteria."
        )


def create_grading_strategy(
    grading_config: GradingConfig,
    config_path: Path | None = None,
) -> GradingStrategy:
    """Factory to create grading strategy from configuration.

    Args:
        grading_config: Grading configuration from task type
        config_path: Base path for loading criteria files

    Returns:
        Appropriate grading strategy instance
    """
    if isinstance(grading_config, FileBasedGrading):
        criteria = grading_config.criteria
        if not criteria and grading_config.criteria_file:
            # Load criteria from file
            if config_path:
                criteria_file = config_path / grading_config.criteria_file
            else:
                criteria_file = Path(grading_config.criteria_file)

            if criteria_file.exists():
                data = load_yaml_files([str(criteria_file)])
                # Convert to Criterion objects
                criteria = [Criterion(name=c["name"], description=c["description"]) for c in data.get("criteria", [])]
        return FileBasedGradingStrategy(criteria)

    if isinstance(grading_config, MessageBasedGrading):
        criteria = grading_config.criteria
        if not criteria and grading_config.criteria_file:
            if config_path:
                criteria_file = config_path / grading_config.criteria_file
            else:
                criteria_file = Path(grading_config.criteria_file)

            if criteria_file.exists():
                data = load_yaml_files([str(criteria_file)])
                criteria = [Criterion(name=c["name"], description=c["description"]) for c in data.get("criteria", [])]
        return MessageBasedGradingStrategy(criteria)

    if isinstance(grading_config, ComparisonGrading):
        return ComparisonGradingStrategy(
            reference=grading_config.reference,
            criteria=grading_config.criteria,
        )

    raise ValueError(f"Unknown grading config type: {type(grading_config)}")

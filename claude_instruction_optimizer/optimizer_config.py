"""Configuration management for the Claude instruction optimizer."""

from typing import Set
from pydantic import BaseModel, Field


class OptimizerConfig(BaseModel):
    """Central configuration for the optimizer."""
    
    # Model configuration
    openai_model: str = Field(default="o3", description="OpenAI model to use for grading and prompt engineering")
    reasoning_effort: str = Field(default="high", description="Reasoning effort level for OpenAI responses")
    
    # Execution limits
    bash_timeout_ms: int = Field(default=10000, description="Timeout for bash commands in milliseconds")
    max_parallel_rollouts: int = Field(default=8, description="Maximum concurrent Claude Code rollouts")
    max_turns: int = Field(default=100, description="Maximum conversation turns for Claude Code")
    
    # Logging configuration
    truncation_length: int = Field(default=80, description="Length to truncate log messages")
    
    # Token management
    max_context_tokens: int = Field(default=140000, description="Maximum tokens before context trimming")
    
    # File filtering
    exclude_dirs: Set[str] = Field(
        default={
            "__pycache__", ".pytest_cache", ".mypy_cache", ".tox",
            ".coverage", ".idea", ".vscode", "node_modules", "venv",
            ".venv", "env", ".env", ".git", ".svn", ".hg", "build",
            "dist", "*.egg-info", ".eggs",
        },
        description="Directories to exclude from file gathering"
    )
    
    exclude_extensions: Set[str] = Field(
        default={
            ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib",
            ".DS_Store", ".swp", ".swo", ".swn", ".swa", ".tmp",
            ".bak", ".cache", ".log",
        },
        description="File extensions to exclude from file gathering"
    )
    
    exclude_files: Set[str] = Field(
        default={"CLAUDE.md", ".gitignore", ".dockerignore"},
        description="Specific files to exclude from file gathering"
    )
    
    class Config:
        """Pydantic configuration."""
        validate_assignment = True
        extra = "forbid"
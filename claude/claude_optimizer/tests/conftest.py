"""Pytest configuration and shared fixtures."""

from pathlib import Path

from pydantic import BaseModel
import pytest
import yaml

from claude_optimizer.config import OptimizerConfig
from claude_optimizer.database.models import create_database


class SeedTask(BaseModel):
    id: str
    prompt: str
    description: str
    docker_image: str
    allowed_tools: list[str]


class GradingCriterion(BaseModel):
    name: str
    description: str
    evaluation_criteria: str


@pytest.fixture
def test_config() -> OptimizerConfig:
    """Create a test configuration."""
    return OptimizerConfig(
        rollouts={"max_parallel": 2, "max_turns": 10, "bash_timeout_ms": 5000},
        prompt_engineer={"model": "gpt-4", "reasoning_effort": "low"},
        grader={"model": "gpt-4", "reasoning_effort": "low"},
        summarizer={"model": "gpt-4", "max_tokens": 1000},
        tokens={
            "max_response_tokens": 1000,
            "reasoning_buffer_tokens": 500,
            "max_context_tokens": 5000,
            "max_files_tokens": 2000,
        },
        truncation={"max_file_size_grading": 1000, "max_file_size_pattern_analysis": 1000, "log_message_length": 50},
        exclude_patterns=["*.log", ".git/", "*.pyc"],
    )


@pytest.fixture
def temp_db():
    session_local = create_database("sqlite:///:memory:")
    session = session_local()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_task_yaml() -> str:
    """Sample task YAML content for testing."""
    return """
- id: test_task_001
  prompt: "Create a Python function that adds two numbers."
  description: "Basic function creation test"
  docker_image: "claude-dev:python"
  allowed_tools: ["Read", "Write", "Edit"]
  pre_task_commands: null
"""


@pytest.fixture
def sample_grader_yaml() -> str:
    """Sample grader YAML content for testing."""
    return """
correctness:
  description: "Evaluates functional correctness of the solution"
  evaluation_criteria: "Check if code produces correct output and handles edge cases."
"""


@pytest.fixture
def sample_seeds_yaml(tmp_path) -> Path:
    seeds = [
        SeedTask(
            id="test_rest_api",
            prompt="Create a REST API client that calls backends A and B in parallel.",
            description="Test REST API implementation",
            docker_image="claude-dev:python",
            allowed_tools=["Read", "Write", "Edit"],
        ),
        SeedTask(
            id="test_config_loader",
            prompt="Build a configuration loader that reads from files, env vars, and CLI.",
            description="Test configuration management",
            docker_image="claude-dev:python",
            allowed_tools=["Read", "Write", "Edit"],
        ),
    ]

    seeds_file = tmp_path / "seeds.yaml"
    with seeds_file.open("w") as f:
        yaml.dump([seed.model_dump() for seed in seeds], f)

    return seeds_file


@pytest.fixture
def sample_graders_yaml(tmp_path) -> Path:
    graders = [
        GradingCriterion(
            name="type_safety_data_design",
            description="Use the type system to make invalid states unrepresentable",
            evaluation_criteria="Type annotations everywhere. Use specific types and enums.",
        ),
        GradingCriterion(
            name="code_quality_clarity",
            description="Code should be readable, modern, and refined",
            evaluation_criteria="Readable code with idiomatic features and early returns.",
        ),
        GradingCriterion(
            name="robustness_error_handling",
            description="Fail fast and loudly on unexpected conditions",
            evaluation_criteria="Catch handleable exceptions only. Let bugs crash.",
        ),
    ]

    graders_file = tmp_path / "graders.yaml"
    with graders_file.open("w") as f:
        yaml.dump({"graders": [grader.model_dump() for grader in graders]}, f)

    return graders_file

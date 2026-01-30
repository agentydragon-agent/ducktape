"""Pytest configuration for inop tests."""

import pytest

from agent_core.testing.mcp.responses import *  # noqa: F403

# Import fixtures from testing modules (replaces deprecated pytest_plugins)
from agent_core.testing.responses import *  # noqa: F403
from inop.config import (
    GraderConfig,
    OptimizerConfig,
    PromptEngineerConfig,
    RolloutConfig,
    SummarizerConfig,
    TokenConfig,
    TruncationConfig,
)


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest-asyncio auto mode."""
    config.option.asyncio_mode = "auto"


@pytest.fixture
def test_config() -> OptimizerConfig:
    """Minimal OptimizerConfig for unit tests."""
    return OptimizerConfig(
        rollouts=RolloutConfig(max_parallel=1, max_turns=10, bash_timeout_ms=5000),
        prompt_engineer=PromptEngineerConfig(model="gpt-4o", reasoning_effort=None),
        grader=GraderConfig(model="gpt-4o", reasoning_effort=None),
        summarizer=SummarizerConfig(model="gpt-4o", max_tokens=1000),
        tokens=TokenConfig(
            max_response_tokens=1000, reasoning_buffer_tokens=500, max_context_tokens=5000, max_files_tokens=2000
        ),
        truncation=TruncationConfig(
            max_file_size_grading=10000, max_file_size_pattern_analysis=10000, log_message_length=200
        ),
        exclude_patterns=["*.log"],
    )

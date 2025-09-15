"""Factory for creating agent runners."""

from typing import Any
from adgn_llm.inop.clients.logging_openai_client import (
    LoggingOpenAIModel,
)
from adgn_llm.inop.runners.base import AgentRunner
from adgn_llm.inop.runners.claude_runner import ClaudeRunner
from adgn_llm.inop.runners.minicodex_runner import MiniCodexRunner


def create_runner(
    runner_name: str,
    runner_configs: dict[str, dict[str, Any]],
    openai_model: LoggingOpenAIModel | None = None,
) -> AgentRunner:
    """Create an agent runner based on configuration.

    Args:
        runner_name: Name of the runner (e.g., "claude", "mini_codex")
        runner_configs: Dictionary of runner configurations from runners.yaml
        openai_client: Optional LoggingOpenAIClient for minicodex

    Returns:
        Instantiated runner

    Raises:
        ValueError: If runner type is unknown
    """
    if runner_name not in runner_configs:
        raise ValueError(f"Unknown runner: {runner_name}")

    runner_config = runner_configs[runner_name]
    runner_type = runner_config["type"]
    config = runner_config.get("config", {})

    # Create runner based on type
    if runner_type == "claude_runner":
        return ClaudeRunner(runner_id=runner_name, config=config)
    if runner_type == "minicodex_runner":
        if openai_model is None:
            raise ValueError("MiniCodexRunner requires openai_model")
        return MiniCodexRunner(
            runner_id=runner_name,
            config=config,
            openai_model=openai_model,
        )
    raise ValueError(f"Unknown runner type: {runner_type}")

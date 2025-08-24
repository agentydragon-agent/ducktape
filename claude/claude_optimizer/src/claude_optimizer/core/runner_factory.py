"""Factory for creating agent runners."""

from typing import Any

from claude_optimizer.core.runners.base import AgentRunner
from claude_optimizer.core.runners.claude_runner import ClaudeRunner
from claude_optimizer.core.runners.minicodex_runner import MiniCodexRunner


def create_runner(
    runner_name: str,
    runner_configs: dict[str, dict[str, Any]],
    openai_client: Any | None = None
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
    
    # Add openai_client to config if provided and it's minicodex
    if runner_type == "minicodex_runner" and openai_client:
        config["openai_client"] = openai_client
    
    # Create runner based on type
    if runner_type == "claude_runner":
        return ClaudeRunner(runner_id=runner_name, config=config)
    elif runner_type == "minicodex_runner":
        return MiniCodexRunner(runner_id=runner_name, config=config)
    else:
        raise ValueError(f"Unknown runner type: {runner_type}")
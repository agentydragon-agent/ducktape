"""Factory for creating agent runners."""

from typing import Any

from adgn.inop.runners.base import AgentRunner
from adgn.inop.runners.claude_runner import ClaudeRunner
from adgn.inop.runners.minicodex_runner import MiniCodexRunner
from adgn.openai_utils.model import OpenAIModelProto


def create_runner(
    runner_name: str, runner_configs: dict[str, dict[str, Any]], openai_model: OpenAIModelProto | None = None
) -> AgentRunner:
    """Create an agent runner based on configuration.

    Args:
        runner_name: Name of the runner (e.g., "claude", "mini_codex")
        runner_configs: Dictionary of runner configurations from runners.yaml
        openai_client: (deprecated) removed; pass OpenAIModelProto via openai_model

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
        return MiniCodexRunner(runner_id=runner_name, config=config, openai_model=openai_model)
    raise ValueError(f"Unknown runner type: {runner_type}")

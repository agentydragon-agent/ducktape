"""Build a Microsoft Agent Framework chat client for an `(api, model)` pair.

`function_invocation_configuration` (e.g. `{"max_iterations": 200}`) is
applied at construction time so callers don't have to mutate the client
afterwards. AF chat clients have no `close()` / async context manager
hooks (verified against the Anthropic / OpenAI / Base classes); the
underlying SDK clients are released by Python's GC at process exit.
"""

from typing import Any

from agent_framework import BaseChatClient, FunctionInvocationConfiguration
from agent_framework.anthropic import AnthropicClient
from agent_framework.openai import OpenAIChatCompletionClient


def build_model_client(
    *, api: str, model: str, function_invocation_configuration: FunctionInvocationConfiguration | None = None
) -> BaseChatClient[Any]:
    kwargs: dict[str, Any] = {"model": model}
    if function_invocation_configuration is not None:
        kwargs["function_invocation_configuration"] = function_invocation_configuration
    if api == "openai":
        return OpenAIChatCompletionClient(**kwargs)
    if api == "anthropic":
        return AnthropicClient(**kwargs)
    raise ValueError(f"Unsupported API: {api!r}")

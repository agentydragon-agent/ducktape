"""Explicit consumer policy over canonical routes; no model facts or naming logic."""

from dataclasses import dataclass

from model_catalog.catalog import (
    ANTHROPIC_SUBSCRIPTION_ROUTES,
    ANTIGRAVITY_FLASH_LITE_ROUTES,
    ANTIGRAVITY_ROUTES,
    GPT6_LUNA_RESPONSES,
    GPT6_RESPONSES_ROUTES,
    HAIKU_API,
    OLLAMA_OPENAI_ROUTES,
    OLLAMA_QWEN_IQ4XS_128K,
    OLLAMA_QWEN_IQ4XS_256K,
    Route,
)


@dataclass(frozen=True)
class HarnessRoutes:
    """Generation-time selections retained until app and ingress settings are emitted."""

    claude: tuple[Route, ...]
    codex: tuple[Route, ...]

    @property
    def all(self) -> tuple[Route, ...]:
        return tuple(dict.fromkeys((*self.claude, *self.codex)))


STAGING_APP_MODELS = HarnessRoutes(
    claude=(*ANTHROPIC_SUBSCRIPTION_ROUTES, *ANTIGRAVITY_ROUTES, *OLLAMA_OPENAI_ROUTES),
    codex=(*GPT6_RESPONSES_ROUTES, *OLLAMA_OPENAI_ROUTES),
)
TESTING_APP_MODELS = HarnessRoutes(
    claude=(HAIKU_API, *ANTIGRAVITY_FLASH_LITE_ROUTES, *OLLAMA_OPENAI_ROUTES),
    codex=(GPT6_LUNA_RESPONSES, *OLLAMA_OPENAI_ROUTES),
)

# Existing runner budgets applied to Claude Code and Codex. They are client
# configuration, not inferred from Ollama num_ctx or proof of serving capacity.
RUNNER_CONTEXT_OVERRIDES = {
    OLLAMA_QWEN_IQ4XS_128K.openai: 128 * 1024,
    OLLAMA_QWEN_IQ4XS_128K.native: 128 * 1024,
    OLLAMA_QWEN_IQ4XS_256K.openai: 256 * 1024,
    OLLAMA_QWEN_IQ4XS_256K.native: 256 * 1024,
}

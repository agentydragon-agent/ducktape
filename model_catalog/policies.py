"""Explicit consumer policy over canonical routes; no model facts or naming logic."""

from dataclasses import dataclass

from model_catalog.catalog import (
    ANTHROPIC_SUBSCRIPTION_ROUTES,
    ANTIGRAVITY_FLASH_LITE,
    ANTIGRAVITY_FLASH_LITE_ROUTES,
    ANTIGRAVITY_PRO,
    ANTIGRAVITY_ROUTES,
    CHATGPT_MESSAGES_ROUTES,
    GEMINI_EMBEDDING_ALIAS,
    GEMINI_EMBEDDING_ROUTES,
    GEMINI_FLASH,
    GEMINI_FLASH_LITE,
    GEMINI_ROUTES,
    GPT6_ASTRA_MESSAGES,
    GPT6_LUNA_MESSAGES,
    GPT6_LUNA_RESPONSES,
    GPT6_MESSAGES_ROUTES,
    GPT6_RESPONSES_ROUTES,
    HAIKU_API,
    HAIKU_SUBSCRIPTION,
    MISTRAL_ROUTES,
    OLLAMA_CHAT_ROUTES,
    OLLAMA_EMBEDDING_ROUTE,
    SONNET_SUBSCRIPTION,
    TANA_HAIKU,
    TANA_ROUTES,
    TANA_SONNET,
    Route,
    RouteAlias,
)

# Keys may admit more routes than a picker offers. In particular, Ollama keys admit
# both wires, but the picker avoids the native adapter's Codex reasoning-option issue.
EMBEDDING_ROUTES: tuple[Route | RouteAlias, ...] = (
    GEMINI_EMBEDDING_ALIAS,
    *GEMINI_EMBEDDING_ROUTES,
    OLLAMA_EMBEDDING_ROUTE,
)
CHEAP_EXPERIMENTS_ROUTES = (
    *GEMINI_ROUTES,
    *ANTIGRAVITY_FLASH_LITE_ROUTES,
    *GEMINI_EMBEDDING_ROUTES,
    *MISTRAL_ROUTES,
    *OLLAMA_CHAT_ROUTES,
    HAIKU_API,
    GPT6_LUNA_MESSAGES,
    GPT6_LUNA_RESPONSES,
)


@dataclass(frozen=True)
class ModelLaneRoutes:
    """Authorization and routing policy for a named group of LiteLLM clients.

    Allowed routes scope virtual keys. Fallbacks are ordered targets of a team's
    wildcard router rule; they must already be allowed and do not grant access.
    An empty fallback tuple means this lane has no configured fallback.
    """

    allowed: tuple[Route | RouteAlias, ...]
    fallbacks: tuple[Route, ...] = ()


# Lane identifiers bind these policies to Terraform keys/teams; a key may combine lanes.
KEY_MODEL_LANES = {
    "gpt6_oai_lane_models": ModelLaneRoutes(allowed=GPT6_RESPONSES_ROUTES),
    "gpt6_codex_client_models": ModelLaneRoutes(allowed=GPT6_MESSAGES_ROUTES),
    "tana_client_models": ModelLaneRoutes(allowed=TANA_ROUTES, fallbacks=(TANA_HAIKU,)),
    "codex_client_models": ModelLaneRoutes(allowed=CHATGPT_MESSAGES_ROUTES, fallbacks=(GPT6_LUNA_MESSAGES,)),
    "claude_client_models": ModelLaneRoutes(allowed=ANTHROPIC_SUBSCRIPTION_ROUTES),
    "embedding_client_models": ModelLaneRoutes(allowed=EMBEDDING_ROUTES),
    "gemini_client_models": ModelLaneRoutes(allowed=GEMINI_ROUTES, fallbacks=(GEMINI_FLASH_LITE,)),
    "antigravity_client_models": ModelLaneRoutes(allowed=ANTIGRAVITY_ROUTES, fallbacks=(ANTIGRAVITY_FLASH_LITE,)),
    "ollama_chat_client_models": ModelLaneRoutes(allowed=OLLAMA_CHAT_ROUTES),
    "cheap_experiments_models": ModelLaneRoutes(allowed=CHEAP_EXPERIMENTS_ROUTES),
}


@dataclass(frozen=True)
class ClaudeWrapperModels:
    primary: Route
    haiku: Route
    key_lane: str
    publish_limits: bool = False
    max_output_override: int | None = None


CLAUDE_WRAPPER_MODELS = {
    "codex-claude": ClaudeWrapperModels(
        GPT6_ASTRA_MESSAGES, GPT6_LUNA_MESSAGES, "codex_client_models", publish_limits=True
    ),
    "litellm-claude": ClaudeWrapperModels(SONNET_SUBSCRIPTION, HAIKU_SUBSCRIPTION, "claude_client_models"),
    "gemini-claude": ClaudeWrapperModels(GEMINI_FLASH, GEMINI_FLASH_LITE, "gemini_client_models", publish_limits=True),
    "antigravity-claude": ClaudeWrapperModels(
        ANTIGRAVITY_PRO,
        ANTIGRAVITY_FLASH_LITE,
        "antigravity_client_models",
        publish_limits=True,
        # Preserve the wrapper's configured 65,536, distinct from this account's
        # published 65,535 output limit. Changing that client policy is separate.
        max_output_override=65_536,
    ),
    "tana-claude": ClaudeWrapperModels(TANA_SONNET, TANA_HAIKU, "tana_client_models"),
}

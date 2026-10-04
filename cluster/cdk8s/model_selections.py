"""Explicit key and picker policy over canonical routes; no model facts or naming logic."""

from dataclasses import dataclass

from cluster.cdk8s.model_rosters import (
    ANTHROPIC_SUBSCRIPTION_ROUTES,
    ANTIGRAVITY_FLASH_LITE_ROUTES,
    ANTIGRAVITY_ROUTES,
    CHATGPT_MESSAGES_ROUTES,
    GEMINI_EMBEDDING_ALIAS,
    GEMINI_EMBEDDING_ROUTES,
    GEMINI_ROUTES,
    GPT6_LUNA_MESSAGES,
    GPT6_LUNA_RESPONSES,
    GPT6_MESSAGES_ROUTES,
    GPT6_RESPONSES_ROUTES,
    HAIKU_API,
    MISTRAL_ROUTES,
    OLLAMA_CHAT_ROUTES,
    OLLAMA_EMBEDDING_ROUTE,
    OLLAMA_OPENAI_ROUTES,
    TANA_ROUTES,
    Route,
    RouteAlias,
)

# Keys may admit more routes than a picker offers. In particular, Ollama keys admit
# both wires, but the picker avoids the native adapter's Codex reasoning-option issue.
EMBEDDING_ROUTES: tuple[Route | RouteAlias, ...] = (GEMINI_EMBEDDING_ALIAS, *GEMINI_EMBEDDING_ROUTES, OLLAMA_EMBEDDING_ROUTE)
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
# The existing Terraform variable's lane names are an output contract, not another
# catalog. Each lane selects objects whose identity and metadata are defined upstream.
KEY_MODEL_ROUTES: dict[str, tuple[Route | RouteAlias, ...]] = {
    "gpt6_oai_lane_models": GPT6_RESPONSES_ROUTES,
    "gpt6_codex_client_models": GPT6_MESSAGES_ROUTES,
    "tana_client_models": TANA_ROUTES,
    "codex_client_models": CHATGPT_MESSAGES_ROUTES,
    "claude_client_models": ANTHROPIC_SUBSCRIPTION_ROUTES,
    "embedding_client_models": EMBEDDING_ROUTES,
    "gemini_client_models": GEMINI_ROUTES,
    "antigravity_client_models": ANTIGRAVITY_ROUTES,
    "ollama_chat_client_models": OLLAMA_CHAT_ROUTES,
    "cheap_experiments_models": CHEAP_EXPERIMENTS_ROUTES,
}


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

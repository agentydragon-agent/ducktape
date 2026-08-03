"""Shared model rosters referenced by LiteLLM cross-configuration tests."""

# Full GLM matrix z.ai serves on the Anthropic endpoint (per
# /api/anthropic/v1/models, 2026-06).
ZAI_ANTHROPIC_MODELS: list[str] = [
    "glm-4.5",
    "glm-4.5-air",
    "glm-4.6",
    "glm-4.7",
    "glm-5",
    "glm-5-turbo",
    "glm-5.1",
    "glm-5.2",
]

# Real Anthropic API roster verified against the authenticated /v1/models
# endpoint. These names are mirrored into Haku OpenClaw and Terraform.
ANTHROPIC_MODELS: list[str] = ["claude-opus-5", "claude-sonnet-5", "claude-fable-5", "claude-haiku-4-5-20251001"]

# The subset exposed in OpenClaw's model picker. OpenClaw's bundled LiteLLM
# provider does not query the proxy's authenticated /v1/models endpoint.
OPENCLAW_CODEX_MODELS: list[str] = ["codex-gpt-5.6-luna", "codex-gpt-5.6-terra", "codex-gpt-5.6-sol"]

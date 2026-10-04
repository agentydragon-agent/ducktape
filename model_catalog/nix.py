"""Model selections and JSON generation for the Nix Claude Code gateway wrappers."""

import json
from pathlib import Path

from model_catalog.catalog import (
    ANTIGRAVITY_FLASH_LITE,
    ANTIGRAVITY_PRO,
    GEMINI_FLASH,
    GEMINI_FLASH_LITE,
    GPT6_ASTRA_MESSAGES,
    GPT6_LUNA_MESSAGES,
    HAIKU_SUBSCRIPTION,
    SONNET_SUBSCRIPTION,
    TANA_HAIKU,
    TANA_SONNET,
    Route,
)
from model_catalog.policies import KEY_MODEL_LANES, ModelLaneRoutes
from util.bazel.workspace import get_build_workspace_directory

OUTPUT_PATH = "model_catalog/claude-wrappers.json"


def _wrapper(
    primary: Route,
    haiku: Route,
    lane: ModelLaneRoutes,
    *,
    publish_limits: bool = False,
    max_output_override: int | None = None,
) -> dict[str, str | int]:
    if primary not in lane.allowed or haiku not in lane.allowed:
        raise ValueError(f"wrapper selects a route outside its key lane: {primary.id}, {haiku.id}")
    config: dict[str, str | int] = {"model": primary.id, "haikuModel": haiku.id}
    if publish_limits:
        context = primary.model.context_window
        output = max_output_override if max_output_override is not None else primary.model.max_output_tokens
        if context is None or output is None:
            raise ValueError(f"missing Claude wrapper limits for {primary.id}")
        config.update(maxContextTokens=context, maxOutputTokens=output)
    return config


def claude_wrapper_models() -> dict[str, dict[str, str | int]]:
    return {
        "codex-claude": _wrapper(
            GPT6_ASTRA_MESSAGES, GPT6_LUNA_MESSAGES, KEY_MODEL_LANES["codex_client_models"], publish_limits=True
        ),
        "litellm-claude": _wrapper(SONNET_SUBSCRIPTION, HAIKU_SUBSCRIPTION, KEY_MODEL_LANES["claude_client_models"]),
        "gemini-claude": _wrapper(
            GEMINI_FLASH, GEMINI_FLASH_LITE, KEY_MODEL_LANES["gemini_client_models"], publish_limits=True
        ),
        "antigravity-claude": _wrapper(
            ANTIGRAVITY_PRO,
            ANTIGRAVITY_FLASH_LITE,
            KEY_MODEL_LANES["antigravity_client_models"],
            publish_limits=True,
            # Client override, distinct from this account's published 65,535 output limit.
            max_output_override=65_536,
        ),
        "tana-claude": _wrapper(TANA_SONNET, TANA_HAIKU, KEY_MODEL_LANES["tana_client_models"]),
    }


def write_config(root: Path) -> None:
    path = root / OUTPUT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(claude_wrapper_models(), indent=2, sort_keys=True) + "\n")


def main() -> None:
    write_config(get_build_workspace_directory())


if __name__ == "__main__":
    main()

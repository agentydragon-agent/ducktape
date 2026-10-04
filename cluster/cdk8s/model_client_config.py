"""Generated model selections consumed by the Nix Claude Code gateway wrappers."""

import json
from pathlib import Path

from cluster.cdk8s.manifest_roots import GENERATED_ROOT
from cluster.cdk8s.model_selections import CLAUDE_WRAPPER_MODELS, KEY_MODEL_ROUTES

OUTPUT_PATH = f"{GENERATED_ROOT}/model-clients/claude-wrappers.json"


def claude_wrapper_models() -> dict[str, dict[str, str | int]]:
    configs: dict[str, dict[str, str | int]] = {}
    for name, selection in CLAUDE_WRAPPER_MODELS.items():
        allowed = KEY_MODEL_ROUTES[selection.key_lane]
        if selection.primary not in allowed or selection.haiku not in allowed:
            raise ValueError(f"{name} selects a route outside {selection.key_lane}")
        config: dict[str, str | int] = {"model": selection.primary.id, "haikuModel": selection.haiku.id}
        if selection.publish_limits:
            context = selection.primary.model.context_window
            output = selection.max_output_override
            if output is None:
                output = selection.primary.model.max_output_tokens
            if context is None or output is None:
                raise ValueError(f"missing Claude wrapper limits for {selection.primary.id}")
            config.update(maxContextTokens=context, maxOutputTokens=output)
        configs[name] = config
    return configs


def write_config(root: Path) -> None:
    path = root / OUTPUT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(claude_wrapper_models(), indent=2, sort_keys=True) + "\n")

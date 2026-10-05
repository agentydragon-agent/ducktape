"""Cross-language consumers receive generated projections of canonical selections."""

import json

import pytest_bazel

from model_catalog.catalog import HAIKU_SUBSCRIPTION, SONNET_SUBSCRIPTION
from model_catalog.nix import OUTPUT_PATH, _wrapper, claude_wrapper_models
from model_catalog.policies import KEY_MODEL_LANES
from util.bazel.runfiles import get_required_path


def test_wrapper_projection_matches_committed_json() -> None:
    assert claude_wrapper_models() == json.loads(get_required_path(f"ducktape/{OUTPUT_PATH}").read_text())


def test_wrapper_can_set_client_budget_without_provider_limits() -> None:
    assert SONNET_SUBSCRIPTION.model.context_window is None
    settings = _wrapper(
        SONNET_SUBSCRIPTION,
        HAIKU_SUBSCRIPTION,
        KEY_MODEL_LANES["claude_client_models"],
        max_context_tokens=128_000,
    )
    assert settings["maxContextTokens"] == 128_000
    assert "maxOutputTokens" not in settings


if __name__ == "__main__":
    pytest_bazel.main()

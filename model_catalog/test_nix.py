"""Cross-language consumers receive generated projections of canonical selections."""

import json

import pytest_bazel

from model_catalog.catalog import ANTIGRAVITY_PRO, SERVED_ROUTES
from model_catalog.nix import OUTPUT_PATH, claude_wrapper_models
from model_catalog.policies import CLAUDE_WRAPPER_MODELS, KEY_MODEL_LANES
from util.bazel.runfiles import get_required_path


def test_wrapper_projection_matches_committed_json() -> None:
    assert claude_wrapper_models() == json.loads(get_required_path(f"ducktape/{OUTPUT_PATH}").read_text())


def test_wrappers_select_served_and_authorized_route_objects() -> None:
    served = {route.id: route for route in SERVED_ROUTES}
    configs = claude_wrapper_models()
    for name, selection in CLAUDE_WRAPPER_MODELS.items():
        for route in (selection.primary, selection.haiku):
            assert served[route.id] == route
            assert route in KEY_MODEL_LANES[selection.key_lane].allowed
        assert configs[name]["model"] == selection.primary.id
        assert configs[name]["haikuModel"] == selection.haiku.id
        if selection.publish_limits:
            assert configs[name]["maxContextTokens"] == selection.primary.model.context_window
            expected_output = selection.max_output_override or selection.primary.model.max_output_tokens
            assert configs[name]["maxOutputTokens"] == expected_output
        else:
            assert "maxContextTokens" not in configs[name]
            assert "maxOutputTokens" not in configs[name]


def test_antigravity_client_override_does_not_rewrite_account_metadata() -> None:
    assert ANTIGRAVITY_PRO.model.max_output_tokens == 65_535
    assert claude_wrapper_models()["antigravity-claude"]["maxOutputTokens"] == 65_536


def test_claude_request_suffix_is_not_a_served_identity() -> None:
    model = claude_wrapper_models()["litellm-claude"]["model"]
    assert isinstance(model, str)
    assert not model.endswith("[1m]")


if __name__ == "__main__":
    pytest_bazel.main()

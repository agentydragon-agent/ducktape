"""Route identity, selection, and LiteLLM artifact contracts."""

from dataclasses import replace

import pytest
import pytest_bazel
import yaml

from cluster.cdk8s.litellm.config import main_proxy_config, model_entry
from cluster.cdk8s.model_rosters import (
    ANTHROPIC_API_ROUTES,
    ANTHROPIC_SUBSCRIPTION_ROUTES,
    ANTIGRAVITY_ROUTES,
    CHATGPT_RESPONSES_ROUTES,
    GEMINI_EMBEDDING_ALIAS,
    GEMINI_EMBEDDING_ROUTES,
    HIDDEN_ALIASES,
    OLLAMA_CHAT_ROUTES,
    SERVED_ROUTES,
    Model,
    Route,
)
from cluster.cdk8s.model_selections import KEY_MODEL_ROUTES, STAGING_APP_MODELS, TESTING_APP_MODELS
from util.bazel.runfiles import get_required_path


def test_proxy_projection_matches_committed_manifest() -> None:
    manifest = get_required_path("ducktape/cluster/k8s/litellm/app/app.k8s.yaml")
    [config_map] = [
        item for item in yaml.safe_load_all(manifest.read_text())
        if item["kind"] == "ConfigMap" and item["metadata"]["name"] == "config"
    ]
    assert main_proxy_config() == yaml.safe_load(config_map["data"]["config.yaml"])


def test_catalog_has_unique_ids_and_aliases_reference_served_routes() -> None:
    by_id = {route.id: route for route in SERVED_ROUTES}
    assert len(by_id) == len(SERVED_ROUTES)
    for alias in (*HIDDEN_ALIASES, GEMINI_EMBEDDING_ALIAS):
        assert by_id[alias.target.id] is alias.target
    assert GEMINI_EMBEDDING_ALIAS.target is GEMINI_EMBEDDING_ROUTES[0]
    assert GEMINI_EMBEDDING_ALIAS.id not in {route.id for route in GEMINI_EMBEDDING_ROUTES}


def test_selections_reference_canonical_objects() -> None:
    by_id = {route.id: route for route in SERVED_ROUTES}
    for selection in (*KEY_MODEL_ROUTES.values(), STAGING_APP_MODELS.all, TESTING_APP_MODELS.all):
        for route in selection:
            assert by_id[route.id] is route


def test_testing_picker_does_not_widen_its_key() -> None:
    admitted = KEY_MODEL_ROUTES["cheap_experiments_models"]
    assert all(route in admitted for route in TESTING_APP_MODELS.all)


def test_staging_picker_does_not_widen_its_key() -> None:
    admitted = (
        *KEY_MODEL_ROUTES["gpt6_oai_lane_models"],
        *KEY_MODEL_ROUTES["claude_client_models"],
        *KEY_MODEL_ROUTES["antigravity_client_models"],
        *KEY_MODEL_ROUTES["ollama_chat_client_models"],
    )
    assert all(route in admitted for route in STAGING_APP_MODELS.all)


def test_picker_is_narrower_than_ollama_key() -> None:
    assert all(route in OLLAMA_CHAT_ROUTES for route in TESTING_APP_MODELS.codex[1:])
    assert any(route not in TESTING_APP_MODELS.all for route in OLLAMA_CHAT_ROUTES)


def test_equal_model_slugs_do_not_collapse_account_routes() -> None:
    subscription, direct = ANTHROPIC_SUBSCRIPTION_ROUTES[0], ANTHROPIC_API_ROUTES[0]
    assert subscription.model is direct.model
    assert subscription.id != direct.id
    assert subscription.upstream.api_key != direct.upstream.api_key
    assert subscription.reasoning_efforts and not direct.reasoning_efforts


def test_unknown_limits_are_not_invented_or_published() -> None:
    unknown_codex = [route for route in CHATGPT_RESPONSES_ROUTES if route.model.context_window is None]
    assert unknown_codex
    for route in unknown_codex:
        assert not route.publish_limits
        assert "max_input_tokens" not in model_entry(route)["model_info"]
    assert any(route.model.context_window is None for route in ANTIGRAVITY_ROUTES)


def test_publishing_unknown_limits_fails() -> None:
    unknown = next(route for route in CHATGPT_RESPONSES_ROUTES if route.model.context_window is None)
    with pytest.raises(ValueError, match="unknown limits"):
        model_entry(replace(unknown, publish_limits=True))


def test_missing_display_name_is_not_prettified_from_a_slug() -> None:
    route = next(route for route in SERVED_ROUTES if isinstance(route, Route))
    with pytest.raises(ValueError, match="no display name"):
        _ = replace(route, model=Model("unknown-model")).display_name


if __name__ == "__main__":
    pytest_bazel.main()

"""Invariants over the generated main-proxy config."""

from dataclasses import replace

import pytest
import pytest_bazel

from cluster.cdk8s.litellm.config import main_proxy_config, model_entry
from model_catalog.catalog import GPT6_LUNA_RESPONSES, RouteAlias


def test_tana_routes_register_the_in_process_provider() -> None:
    config = main_proxy_config()
    tana_entries = [entry for entry in config["model_list"] if entry["model_name"].startswith("tana/")]

    assert tana_entries
    assert all(entry["litellm_params"]["custom_llm_provider"] == "tana" for entry in tana_entries)
    assert any(item["provider"] == "tana" for item in config["litellm_settings"]["custom_provider_map"])


@pytest.mark.parametrize("publish", [False, True])
def test_token_override_projection_uses_one_output_value(publish: bool) -> None:
    route = replace(
        GPT6_LUNA_RESPONSES,
        model=replace(GPT6_LUNA_RESPONSES.model, context_window=111_111, max_output_tokens=22_222),
        publish_limits=publish,
    )
    expected = {"max_input_tokens": 111_111, "max_output_tokens": 22_222, "max_tokens": 22_222} if publish else {}
    for entry in (route, RouteAlias("compatibility-alias", route)):
        info = model_entry(entry)["model_info"]
        assert {key: value for key, value in info.items() if key in ("max_input_tokens", "max_output_tokens", "max_tokens")} == expected
        assert "context_window" not in info


if __name__ == "__main__":
    pytest_bazel.main()

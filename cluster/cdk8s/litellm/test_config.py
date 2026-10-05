"""Invariants over the generated main-proxy config."""

import pytest_bazel

from cluster.cdk8s.litellm.config import main_proxy_config


def test_tana_routes_register_the_in_process_provider() -> None:
    config = main_proxy_config()
    tana_entries = [entry for entry in config["model_list"] if entry["model_name"].startswith("tana/")]

    assert tana_entries
    assert all(entry["litellm_params"]["custom_llm_provider"] == "tana" for entry in tana_entries)
    assert any(item["provider"] == "tana" for item in config["litellm_settings"]["custom_provider_map"])


if __name__ == "__main__":
    pytest_bazel.main()

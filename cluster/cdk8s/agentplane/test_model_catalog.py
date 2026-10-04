"""The app's public catalog is a projection, not an independently authored roster."""

import pytest
import pytest_bazel
import yaml

from cluster.cdk8s.agentplane import staging_config, testing_config
from cluster.cdk8s.agentplane.environment import Environment
from cluster.cdk8s.agentplane.staging import ENV as STAGING
from cluster.cdk8s.agentplane.testing import ENV as TESTING
from util.bazel.runfiles import get_required_path


@pytest.mark.parametrize("namespace", ["agentplane-staging", "agentplane-testing"])
def test_app_catalog_matches_committed_config(namespace: str) -> None:
    manifest = get_required_path(f"ducktape/cluster/generated/{namespace}/{namespace}.k8s.yaml")
    [config_map] = [
        item for item in yaml.safe_load_all(manifest.read_text())
        if item["kind"] == "ConfigMap" and item["metadata"]["name"] == "agentplane-app-config"
    ]
    committed = yaml.safe_load(config_map["data"]["config.yaml"])
    config = staging_config.config() if namespace == "agentplane-staging" else testing_config.config()
    assert config.models.model_dump(mode="json") == committed["models"]
    assert {name: preset.model for name, preset in config.thread_presets.items()} == {
        name: preset["model"] for name, preset in committed["thread_presets"].items()
    }


@pytest.mark.parametrize("env", [STAGING, TESTING], ids=["staging", "testing"])
def test_environment_retains_the_catalog_source(env: Environment) -> None:
    assert [route.id for route in env.model_routes.all] == [option.model for option in env.app_config.models.models]


if __name__ == "__main__":
    pytest_bazel.main()

"""Authorization and routing policy at the Terraform serialization boundary."""

from dataclasses import replace

import pytest
import pytest_bazel
import yaml

from cluster.cdk8s.litellm.keys import model_lanes
from model_catalog.catalog import GPT6_ASTRA_MESSAGES, TANA_HAIKU
from model_catalog.policies import KEY_MODEL_LANES, ModelLaneRoutes
from util.bazel.runfiles import get_required_path


def test_lanes_match_committed_terraform_inputs() -> None:
    path = get_required_path("ducktape/cluster/k8s/litellm/keys-tf/keys-tf.k8s.yaml")
    [resource] = yaml.safe_load_all(path.read_text())
    variables = {entry["name"]: entry["value"] for entry in resource["spec"]["vars"]}
    assert {name: lane.model_dump() for name, lane in model_lanes(KEY_MODEL_LANES).items()} == variables["model_lanes"]


def test_lane_cannot_authorize_an_unserved_route() -> None:
    route = replace(TANA_HAIKU, model=replace(TANA_HAIKU.model, id="not-served"))
    with pytest.raises(ValueError, match="unserved routes"):
        model_lanes({"invalid": ModelLaneRoutes(allowed=(route,))})


def test_fallback_does_not_grant_access() -> None:
    with pytest.raises(ValueError, match="fallback routes outside its allowlist"):
        model_lanes({"invalid": ModelLaneRoutes(allowed=(TANA_HAIKU,), fallbacks=(GPT6_ASTRA_MESSAGES,))})


if __name__ == "__main__":
    pytest_bazel.main()

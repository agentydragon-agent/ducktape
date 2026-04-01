"""Verify generated buildbuddy.yaml is up to date with generate_buildbuddy.py."""

import pytest_bazel
import yaml

from devinfra.ci.generate_buildbuddy import generate_buildbuddy_config
from util.bazel.runfiles import get_required_path

_BUILDBUDDY_YAML_RLOCATION = "_main/buildbuddy.yaml"


def test_buildbuddy_yaml_up_to_date() -> None:
    current = yaml.safe_load(get_required_path(_BUILDBUDDY_YAML_RLOCATION).read_text())
    expected = generate_buildbuddy_config()
    assert current == expected, (
        "buildbuddy.yaml is out of date. Run 'bazel run //devinfra/ci:generate_buildbuddy_bin' to update."
    )


if __name__ == "__main__":
    pytest_bazel.main()

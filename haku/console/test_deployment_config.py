"""Contracts for the deploy-owned Haku Console configuration."""

import pytest_bazel
import yaml

from haku.console.mcp_config import ConsoleConfigFile
from util.bazel.runfiles import get_required_path


def test_deployed_console_config_is_valid() -> None:
    raw = yaml.safe_load(get_required_path("ducktape/cluster/k8s/haku/console/config.yaml").read_text())
    config = ConsoleConfigFile.model_validate(raw)

    assert config.kubernetes_authorization is not None
    subject = config.kubernetes_authorization.subjects_by_access_profile["public-coder"]
    assert subject.username == "haku:access-profile:public-coder"
    assert subject.groups == ("haku:access-profile:public-coder", "system:authenticated")


if __name__ == "__main__":
    pytest_bazel.main()

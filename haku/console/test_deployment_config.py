"""Contracts for the deploy-owned Haku Console configuration."""

import pytest_bazel
import yaml

from haku.console.mcp_config import ConsoleConfigFile
from util.bazel.runfiles import get_required_path


def test_deployed_console_config_is_valid() -> None:
    raw = yaml.safe_load(get_required_path("ducktape/cluster/k8s/haku/console/config.yaml").read_text())
    config = ConsoleConfigFile.model_validate(raw)

    profiles = {profile.id: profile for profile in config.access_profiles}
    assert profiles["haku"].in_process_server_ids == {"haku_conversations", "kubernetes"}

    assert config.kubernetes_authorization is not None
    subjects = config.kubernetes_authorization.subjects_by_access_profile
    assert subjects["haku"].username == "haku:access-profile:haku"
    assert subjects["haku"].groups == ("haku:access-profile:haku", "system:authenticated")
    assert subjects["public-coder"].username == "haku:access-profile:public-coder"
    assert subjects["public-coder"].groups == ("haku:access-profile:public-coder", "system:authenticated")

    policies = {policy["id"]: policy for policy in raw["auto_approval_policies"]}
    assert policies["kubernetes_reads"]["tools"] == {"kubernetes": ["can_i", "list_grants", "get_grant"]}
    assert "kubernetes_reads" in policies["haku_v1"]["policies"]
    assert "kubernetes_reads" in policies["public_coder_safe_reads"]["policies"]


if __name__ == "__main__":
    pytest_bazel.main()

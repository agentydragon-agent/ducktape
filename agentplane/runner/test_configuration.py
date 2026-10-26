"""The shared file contract rejects partial and contradictory deployment policy."""

import pytest
import pytest_bazel
from pydantic import ValidationError

from agentplane.runner.configuration import Configuration


def _configuration() -> dict[str, object]:
    return {
        "version": 1,
        "state_dir": "/test/state",
        "initialization_cwd": "/test/workspaces",
        "control": {"target": "gateway.test:7100", "bearer": "control-placeholder"},
        "ingress": {"target": "history.test:8081", "bearer": "ingress-placeholder"},
        "platform_instructions": "Test guidance.",
        "harness_environment": {"inherit": ["PATH"], "values": {"HOME": "/test/home"}},
        "codex": {"binary": "/test/codex", "base_url": "http://models.test/v1", "token_env": "TEST_PROVIDER_TOKEN"},
    }


def test_runner_configuration_round_trip_preserves_environment_sources() -> None:
    config = Configuration.model_validate(_configuration())
    decoded = Configuration.model_validate_json(config.model_dump_json(exclude_none=True))
    assert decoded == config
    assert decoded.harness_environment.values["HOME"] == "/test/home"
    assert decoded.harness_environment.inherit == ["PATH"]


@pytest.mark.parametrize(
    "updates",
    [
        {"version": 2},
        {"state_dir": "relative"},
        {"workspace_root": ""},
        {"harness_environment": {"inherit": ["NAME=value"]}},
        {"harness_environment": {"values": {"": "value"}}},
        {"codex": {"binary": "/test/codex"}},
        {"executor": {"kind": "container", "url": "ws://127.0.0.1:4501"}},
        {"executor": {"kind": "container", "url": "ws://0.0.0.0:4501", "socket": "/test/socket"}},
        {"executor": {"kind": "container", "url": "ws://127.0.0.1:0", "socket": "/test/socket"}},
        {"executor": {"kind": "container", "url": "ws://127.0.0.1:4501?", "socket": "/test/socket"}},
        {"executor": {"kind": "container", "url": "ws://127.0.0.1:4501", "socket": "/test/socket", "isolation": {}}},
        {"executor": {"kind": "unknown"}},
        {"unexpected": "value"},
    ],
)
def test_configuration_rejects_invalid_policy(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Configuration.model_validate(_configuration() | updates)


if __name__ == "__main__":
    pytest_bazel.main()

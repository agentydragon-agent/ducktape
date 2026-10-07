"""Deployment settings: YAML, nested environment overrides and invalid configuration."""

from pathlib import Path

import pytest
import pytest_bazel
from pydantic import ValidationError

from agentplane.notification_service.settings import (
    CONFIG_FILE_ENV,
    NoticeDebounceSettings,
    SandboxServiceSettings,
    Settings,
)


def test_yaml_settings_and_nested_environment_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "settings.yaml"
    config.write_text("""namespace: test
actions:
  url: http://actions
  token_file: /tokens/actions
notice_debounce:
  quiet_seconds: 3
  max_wait_seconds: 15
sandbox_service:
  target: sandboxes:8080
  token_file: /tokens/sandboxes
""")
    monkeypatch.setenv(CONFIG_FILE_ENV, str(config))
    monkeypatch.setenv("AGENTPLANE_NOTIFICATIONS_DATABASE_URL", "postgresql://unused")
    settings = Settings(_cli_parse_args=False)
    assert settings.notice_debounce == NoticeDebounceSettings(quiet_seconds=3, max_wait_seconds=15)
    assert settings.actions.url == "http://actions"
    assert settings.actions.token_file == Path("/tokens/actions")
    assert settings.sandbox_service.target == "sandboxes:8080"
    assert settings.sandbox_service.token_file == Path("/tokens/sandboxes")
    assert settings.sandbox_service.command_admission_timeout_s == 20
    assert settings.sandbox_service.request_timeout_s == 5
    assert settings.sandbox_service.lifecycle_timeout_s == 310
    assert settings.sandbox_service.follow_timeout_s == 960
    monkeypatch.setenv("AGENTPLANE_NOTIFICATIONS_ACTIONS__URL", "http://overridden-actions")
    monkeypatch.setenv("AGENTPLANE_NOTIFICATIONS_SANDBOX_SERVICE__TARGET", "overridden-sandboxes:8080")
    monkeypatch.setenv("AGENTPLANE_NOTIFICATIONS_NOTICE_DEBOUNCE__QUIET_SECONDS", "0")
    monkeypatch.setenv("AGENTPLANE_NOTIFICATIONS_SANDBOX_SERVICE__COMMAND_ADMISSION_TIMEOUT_S", "22")
    monkeypatch.setenv("AGENTPLANE_NOTIFICATIONS_SANDBOX_SERVICE__REQUEST_TIMEOUT_S", "7")
    settings = Settings(_cli_parse_args=False)
    assert settings.notice_debounce == NoticeDebounceSettings(quiet_seconds=0, max_wait_seconds=15)
    assert settings.actions.url == "http://overridden-actions"
    assert settings.sandbox_service.target == "overridden-sandboxes:8080"
    assert settings.sandbox_service.command_admission_timeout_s == 22
    assert settings.sandbox_service.request_timeout_s == 7
    assert settings.sandbox_service.token_file == Path("/tokens/sandboxes")
    with config.open("a") as file:
        file.write("unknown_setting: true\n")
    with pytest.raises(ValidationError, match="Extra inputs"):
        Settings(_cli_parse_args=False)
    config.unlink()
    with pytest.raises(ValueError, match="regular file"):
        Settings(_cli_parse_args=False)


@pytest.mark.parametrize(
    "values",
    [
        {"quiet_seconds": -1},
        {"quiet_seconds": float("nan")},
        {"quiet_seconds": float("inf")},
        {"max_wait_seconds": 0},
        {"max_wait_seconds": -1},
        {"max_wait_seconds": float("inf")},
    ],
)
def test_invalid_notice_debounce(values: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        NoticeDebounceSettings(**values)


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_command_admission_timeout(timeout: float) -> None:
    with pytest.raises(ValidationError):
        SandboxServiceSettings(
            target="sandboxes:8080", token_file=Path("/tokens/sandboxes"), command_admission_timeout_s=timeout
        )


@pytest.mark.parametrize("name", ["request_timeout_s", "lifecycle_timeout_s", "follow_timeout_s"])
@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_sandbox_service_deadline(name: str, timeout: float) -> None:
    with pytest.raises(ValidationError):
        SandboxServiceSettings.model_validate(
            {"target": "sandboxes:8080", "token_file": "/tokens/sandboxes", name: timeout}
        )


def test_notice_debounce_defaults() -> None:
    assert NoticeDebounceSettings().model_dump() == {"quiet_seconds": 2, "max_wait_seconds": 10}


if __name__ == "__main__":
    pytest_bazel.main()

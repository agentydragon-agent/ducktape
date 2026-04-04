"""Tests for LoggedContainer: verify log persistence across success, failure, and error."""

from pathlib import Path

import pytest
import pytest_bazel

from third_party.debian_slim.rlocations import IMAGE_TAG as DEBIAN_IMAGE_TAG, TARBALL as DEBIAN_TARBALL
from util.oci import load_image
from util.testing.container_logs import LoggedContainer
from util.testing.undeclared_outputs import undeclared_outputs_dir


def _logs_dir(test_name: str) -> Path:
    return undeclared_outputs_dir() / test_name


def test_logs_collected_on_success() -> None:
    """Verify LoggedContainer persists main process logs on success."""
    load_image(DEBIAN_TARBALL)
    with LoggedContainer(DEBIAN_IMAGE_TAG, test_name="logs-success", command="echo SUCCESS_LOG_LINE"):
        pass  # container exits after echo

    stdout = _logs_dir("logs-success") / "stdout.log"
    assert stdout.exists(), "stdout.log not written on success"
    assert b"SUCCESS_LOG_LINE" in stdout.read_bytes()


def test_logs_collected_on_exec_failure() -> None:
    """Verify LoggedContainer persists logs even when an assertion fails inside the with block."""
    load_image(DEBIAN_TARBALL)

    def _run() -> None:
        with LoggedContainer(DEBIAN_IMAGE_TAG, test_name="logs-failure", command="sleep infinity") as container:
            container.exec("echo FAILURE_LOG_LINE")
            raise AssertionError("deliberate failure")

    with pytest.raises(AssertionError):
        _run()

    stdout = _logs_dir("logs-failure") / "stdout.log"
    assert stdout.exists(), "stdout.log not written on failure"


def test_logs_collected_on_container_error() -> None:
    """Verify LoggedContainer persists logs when the container command fails."""
    load_image(DEBIAN_TARBALL)
    with LoggedContainer(DEBIAN_IMAGE_TAG, test_name="logs-error", command="bash -c 'echo ERROR_LINE && exit 1'"):
        pass  # container exits immediately with error

    stdout = _logs_dir("logs-error") / "stdout.log"
    stderr = _logs_dir("logs-error") / "stderr.log"
    assert stdout.exists() or stderr.exists(), "no logs written on container error"


if __name__ == "__main__":
    pytest_bazel.main()

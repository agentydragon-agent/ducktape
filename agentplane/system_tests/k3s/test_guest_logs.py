"""Guest log retention across launcher removal and container log replacement."""

from pathlib import Path

import pytest_bazel
from tenacity import Retrying, stop_after_delay, wait_fixed

from agentplane.system_tests.k3s.guest_logs import capture


def test_retains_unlinked_logs_and_new_incarnations(tmp_path: Path) -> None:
    logs, outputs = tmp_path / "pods", tmp_path / "artifacts"
    source = logs / "systest_virt-launcher-test_uid-one" / "guest-console-log" / "0.log"
    source.parent.mkdir(parents=True)
    other = logs / "other_virt-launcher-test_uid-two" / "guest-console-log" / "0.log"
    other.parent.mkdir(parents=True)
    other.write_text("OUTSIDE_NAMESPACE\n")

    def wait_for(text: str) -> None:
        for attempt in Retrying(stop=stop_after_delay(5), wait=wait_fixed(0.01), reraise=True):
            with attempt:
                assert text in "".join(path.read_text() for path in outputs.rglob("*.log"))

    with capture(log_root=logs, namespace="systest", destination=outputs), source.open("w") as original:
        original.write("BOOT\n")
        original.flush()
        wait_for("BOOT")
        source.unlink()
        original.write("AFTER_UNLINK\n")
        original.flush()
        wait_for("AFTER_UNLINK")
        source.write_text("NEW_CONTAINER\n")
        wait_for("NEW_CONTAINER")
        replacement = logs / "systest_virt-launcher-test_uid-three" / "guest-console-log" / "0.log"
        replacement.parent.mkdir(parents=True)
        replacement.write_text("NEW_LAUNCHER\n")
        wait_for("NEW_LAUNCHER")

    assert sorted(path.read_text() for path in outputs.rglob("*.log")) == [
        "BOOT\nAFTER_UNLINK\n",
        "NEW_CONTAINER\n",
        "NEW_LAUNCHER\n",
    ]


if __name__ == "__main__":
    pytest_bazel.main()

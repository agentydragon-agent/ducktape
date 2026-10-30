"""Executable vm_systemd scenarios sharing one k3s stack."""

from __future__ import annotations

import pytest
import pytest_bazel

from agentplane.system_tests.sandbox import Sandboxes
from agentplane.system_tests.scenarios import runner_systemd


@pytest.mark.vm_sandboxes
async def test_real_systemd_supervision(sandbox: Sandboxes) -> None:
    await runner_systemd.real_systemd_supervision(sandbox)


if __name__ == "__main__":
    pytest_bazel.main()

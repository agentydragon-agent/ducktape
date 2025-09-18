from __future__ import annotations

import pytest

from adgn.seatbelt.runner import run_sandboxed


@pytest.mark.macos
@pytest.mark.shell
def test_minimal_true_exits_zero(restrictive_echo_policy):
    # Minimal restrictive policy should be sufficient for /usr/bin/true
    res = run_sandboxed(restrictive_echo_policy, ["/usr/bin/true"])
    assert res.exit_code == 0

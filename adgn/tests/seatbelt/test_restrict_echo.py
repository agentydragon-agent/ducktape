import pytest

from adgn.seatbelt.model import FileRule, PathFilter, ProcessRule, SBPLPolicy
from adgn.seatbelt.runner import run_sandboxed


@pytest.fixture
def restrictive_echo_policy() -> SBPLPolicy:
    return SBPLPolicy(
        default_behavior="deny",
        process=ProcessRule(allow_process_star=True, allow_signal_self=True),
        files=[
            FileRule(op="file-map-executable", filters=[]),
            FileRule(op="file-read*", filters=[PathFilter(kind="subpath", value="/")]),
        ],
    )


@pytest.mark.macos
@pytest.mark.shell
def test_exec_minimal_restrictive_echo(restrictive_echo_policy: SBPLPolicy):
    res = run_sandboxed(restrictive_echo_policy, ["/bin/echo", "HELLO_MINIMAL"])
    assert res.exit_code == 0
    assert res.stdout == b"HELLO_MINIMAL\n"

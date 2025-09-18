import pytest

from adgn.seatbelt.model import FileRule, PathFilter, ProcessRule, SBPLPolicy
from adgn.seatbelt.runner import run_sandboxed


@pytest.fixture
def allow_all_policy() -> SBPLPolicy:
    return SBPLPolicy(
        default_behavior="allow",
        process=ProcessRule(allow_process_star=True, allow_signal_self=True),
        files=[
            FileRule(op="file-map-executable", filters=[]),
            FileRule(op="file-read*", filters=[PathFilter(kind="subpath", value="/")]),
            FileRule(op="file-write*", filters=[PathFilter(kind="subpath", value="/")]),
        ],
    )


@pytest.mark.macos
@pytest.mark.shell
def test_exec_allow_all_runs_echo(allow_all_policy: SBPLPolicy):
    res = run_sandboxed(allow_all_policy, ["/bin/sh", "-c", "echo ALLOW_ALL_OK"])
    assert res.exit_code == 0
    assert res.stdout == b"ALLOW_ALL_OK\n"

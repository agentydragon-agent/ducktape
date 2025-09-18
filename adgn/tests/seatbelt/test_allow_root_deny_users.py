import pytest

from adgn.seatbelt.model import FileRule, PathFilter, ProcessRule, SBPLPolicy
from adgn.seatbelt.runner import run_sandboxed


@pytest.fixture
def policy_deny_users() -> SBPLPolicy:
    base = SBPLPolicy(
        default_behavior="allow",
        process=ProcessRule(allow_process_star=True, allow_signal_self=True),
        files=[
            FileRule(op="file-map-executable", filters=[]),
            FileRule(op="file-read*", filters=[PathFilter(kind="subpath", value="/")]),
            FileRule(op="file-write*", filters=[PathFilter(kind="subpath", value="/")]),
        ],
    )
    # Carve-out deny /Users
    base.files += [
        FileRule(
            op="file-read*",
            action="deny",
            filters=[PathFilter(kind="subpath", value="/Users")],
        ),
        FileRule(
            op="file-read-metadata",
            action="deny",
            filters=[PathFilter(kind="subpath", value="/Users")],
        ),
    ]
    return base


@pytest.mark.macos
@pytest.mark.shell
def test_exec_allow_root_deny_users(policy_deny_users: SBPLPolicy):
    ok = run_sandboxed(policy_deny_users, ["/bin/sh", "-c", "ls /System"])
    assert ok.exit_code == 0

    deny = run_sandboxed(policy_deny_users, ["/bin/sh", "-c", "ls /Users"])
    assert deny.exit_code != 0

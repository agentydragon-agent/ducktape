from adgn.seatbelt.model import SBPLPolicy
from adgn.seatbelt.runner import run_sandboxed_async
from tests._markers import REQUIRES_SANDBOX_EXEC

pytestmark = [*REQUIRES_SANDBOX_EXEC]

# policy_deny_users fixture is provided by conftest.py


async def test_exec_allow_root_deny_users(policy_deny_users: SBPLPolicy):
    ok = await run_sandboxed_async(policy_deny_users, ["/bin/sh", "-c", "ls /System"])
    assert ok.exit_code == 0

    deny = await run_sandboxed_async(policy_deny_users, ["/bin/sh", "-c", "ls /Users"])
    assert deny.exit_code != 0

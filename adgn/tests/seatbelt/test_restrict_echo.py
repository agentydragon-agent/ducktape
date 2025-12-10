from adgn.seatbelt.model import SBPLPolicy
from adgn.seatbelt.runner import run_sandboxed_async
from tests._markers import REQUIRES_SANDBOX_EXEC

pytestmark = [*REQUIRES_SANDBOX_EXEC]

# Note: restrictive_echo_policy fixture is provided in tests/seatbelt/conftest.py


async def test_exec_minimal_restrictive_echo(restrictive_echo_policy: SBPLPolicy):
    res = await run_sandboxed_async(restrictive_echo_policy, ["/bin/echo", "HELLO_MINIMAL"])
    assert res.exit_code == 0
    assert res.stdout == b"HELLO_MINIMAL\n"

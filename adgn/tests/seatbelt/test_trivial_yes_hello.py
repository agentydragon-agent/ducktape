from __future__ import annotations

import pytest

from adgn.seatbelt.runner import run_sandboxed_async


@pytest.mark.macos
@pytest.mark.shell
@pytest.mark.asyncio
async def test_trivial_yes_hello_world(allow_all_policy):
    res = await run_sandboxed_async(allow_all_policy, ["/bin/sh", "-c", "yes hello | head -n 5"])
    assert res.exit_code == 0
    assert b"hello" in res.stdout or b"hello" in (res.stderr or b"")

from __future__ import annotations

import sys

import pytest

from adgn.seatbelt.runner import run_sandboxed_async


@pytest.mark.macos
@pytest.mark.shell
@pytest.mark.asyncio
async def test_python_print_ok(allow_all_policy):
    res = await run_sandboxed_async(
        allow_all_policy,
        [sys.executable, "-c", "print('PYOK')"],
    )
    assert res.exit_code == 0
    assert res.stdout == b"PYOK\n"

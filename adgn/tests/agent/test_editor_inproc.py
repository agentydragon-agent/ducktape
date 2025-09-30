from __future__ import annotations

from pathlib import Path

import pytest

from adgn.mcp.editor_server import (
    DoneInput,
    Success,
    ReadInfoResult,
    ReplaceTextResult,
)


@pytest.mark.asyncio
async def test_editor_inproc_basic_ops(typed_editor_factory) -> None:
    async with typed_editor_factory() as (client, target):
        # read_info works (typed via introspected Input model)
        ReadInfoInput = client.models["read_info"].Input
        info = await client.read_info(ReadInfoInput())
        assert isinstance(info, ReadInfoResult)
        assert info.ok is True
        assert info.lines == 1
        assert Path(info.path) == target

        # replace_text modifies buffer (x=1 → x=2)
        ReplaceInput = client.models["replace_text"].Input
        sc = await client.replace_text(ReplaceInput(old_text="x = 1", new_text="x = 2"))
        assert isinstance(sc, ReplaceTextResult)
        assert sc.ok is True

        # done(success=True) runs syntax check for .py and saves
        result = await client.done(DoneInput(outcome="success", summary=None))
        # FastMCP may wrap outputs under a top-level model (e.g., doneOutput.result)
        unwrapped = getattr(result, "result", result)
        assert isinstance(unwrapped, Success)
        assert unwrapped.kind == "Success"

    # File should be persisted with new content
    assert Path(target).read_text(encoding="utf-8") == "x = 2\n"

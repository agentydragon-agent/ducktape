from __future__ import annotations

from collections.abc import Awaitable, Callable
import os
from pathlib import Path
from typing import Any

import pytest

from adgn.llm.llm_edit import _execute
from adgn.llm.openai_utils.model import ResponsesRequest

from tests.fixtures.responses import ResponsesFactory
from ..support.openai_mock import LIVE


def make_edit_behavior() -> Callable[..., Awaitable[Any]]:
    """Behavior that drives editor: replace_text -> save -> done(success)."""
    step = {"i": 0}
    rf = ResponsesFactory(os.getenv("OPENAI_MODEL", "o4-mini"))

    async def behavior(req: Any) -> Any:
        # Accept either raw dicts (legacy) or our typed ResponsesRequest
        assert isinstance(req, (dict, ResponsesRequest)), (
            f"unexpected request type: {type(req)!r}"
        )
        i = step["i"]
        step["i"] = i + 1
        if i == 0:
            return rf.make(
                rf.tool_call(
                    "mcp__editor__replace_text",
                    {"old_text": "HELLO_WORLD", "new_text": "GOODBYE_WORLD"},
                )
            )
        if i == 1:
            return rf.make(rf.tool_call("mcp__editor__save", {}))
        if i == 2:
            # Inspect buffer to verify content before done
            return rf.make(
                rf.tool_call("mcp__editor__read_line_range", {"start": 1, "end": 1})
            )
        if i == 3:
            return rf.make(
                rf.tool_call(
                    "mcp__editor__done",
                    {"payload": {"outcome": "success", "summary": "ok"}},
                )
            )
        return rf.make_assistant_message("done")

    return behavior


# Shared trunk: run with mock (behavior) and live (LIVE sentinel)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "openai_client_param",
    [
        pytest.param(make_edit_behavior(), id="mock"),
        pytest.param(LIVE, id="live", marks=pytest.mark.live_llm),
    ],
    indirect=True,
)
async def test_llm_edit_obvious_replace(openai_client_param, tmp_path: Path) -> None:
    # Prepare a simple file with an obvious single replace target
    p = tmp_path / "sample.txt"
    p.write_text("HELLO_WORLD\n", encoding="utf-8")

    prompt = (
        "Replace the exact text HELLO_WORLD with GOODBYE_WORLD in the file. "
        "Call exactly these tools in order, and no others: "
        "1) mcp__editor__replace_text with old_text='HELLO_WORLD' and new_text='GOODBYE_WORLD' (do NOT use replace_text_all); "
        "2) mcp__editor__save; "
        "3) mcp__editor__done with payload.outcome='success' and payload.summary='ok'."
    )

    code = await _execute(
        file_path=p,
        prompt=prompt,
        model=os.getenv("OPENAI_MODEL", "o4-mini"),
        reasoning_effort=None,
        reasoning_summary=None,
        client=openai_client_param,
    )
    assert code == 0
    text = p.read_text(encoding="utf-8")
    print("[debug] final file content:\n" + text)
    assert "GOODBYE_WORLD" in text
    assert "HELLO_WORLD" not in text

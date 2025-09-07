from __future__ import annotations

import os
from pathlib import Path

import openai
import pytest


# Live LLM test: uses real OpenAI API via environment credentials
# Marker for selective runs: -k live_llm
@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_llm_edit_live_obvious_replace(tmp_path: Path) -> None:
    # Prepare a simple file with an obvious single replace target
    p = tmp_path / "sample.txt"
    p.write_text("HELLO_WORLD\n", encoding="utf-8")

    # Strong, explicit instruction to drive deterministic tool use
    prompt = (
        "Replace the exact text HELLO_WORLD with GOODBYE_WORLD in the file. "
        "Use the editor.replace_text tool exactly once, then call save, then done(success=true, report='ok')."
    )

    # Invoke inner execution function directly (no sys/argv)
    from adgn_llm.llm_edit import _execute

    model = os.getenv("OPENAI_MODEL", "o4-mini")
    code = await _execute(
        file_path=p,
        prompt=prompt,
        model=model,
        reasoning_effort=None,
        reasoning_summary=None,
        client=openai.AsyncOpenAI(),
    )
    assert code == 0, "Execution should complete with code 0"
    # Verify the edit actually happened on disk
    text = p.read_text(encoding="utf-8")
    assert "GOODBYE_WORLD" in text
    assert "HELLO_WORLD" not in text

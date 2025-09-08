#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure repo dir is on sys.path for local imports
THIS_DIR = Path(__file__).resolve().parent
EVAL_DIR = THIS_DIR.parent
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from run_eval import read_dataset  # type: ignore
from schemas import CrushSample  # type: ignore

ROOT = EVAL_DIR
DATA = ROOT / "data" / "_test"


from hamcrest import (
    any_of,
    assert_that,
    contains_string,
    equal_to,
    has_entries,
    has_item,
)


@pytest.mark.asyncio
async def test_read_ccr_min():
    ds = await read_dataset(DATA / "ccr_min.jsonl")
    assert len(ds) == 2
    s = ds[0]
    assert s.correlation_id == "ccr-1"
    msgs = s.anthropic_request.messages
    assert_that(msgs[0]["role"], equal_to("user"))
    # last user message should contain the <bad> marker
    last_user = next(m for m in reversed(msgs) if m.get("role") == "user")
    # Matcher: has a content block that is text with substring
    assert_that(
        last_user,
        has_entries(
            content=any_of(
                has_item(has_entries(type="text", text=contains_string("<bad>"))),
                # Some datasets encode content as a plain string
                contains_string("<bad>"),
            ),
        ),
    )


@pytest.mark.asyncio
async def test_read_crush_min():
    ds = await read_dataset(DATA / "crush_min.jsonl")
    assert len(ds) == 2
    s_bad = ds[0]
    # crush has no correlation_id semantics
    assert s_bad.correlation_id is None
    # Should be a CrushSample discriminated instance
    assert isinstance(s_bad, CrushSample)
    # Responses-native payload preserved
    raw = s_bad.oai_request
    payload = raw if isinstance(raw, dict) else raw.model_dump()
    assert isinstance(payload.get("input"), list)
    roles = [
        (it.get("role") or "").lower()
        for it in payload.get("input")
        if isinstance(it, dict)
    ]
    assert any(r in ("user", "assistant") for r in roles)

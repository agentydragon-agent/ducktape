#!/usr/bin/env python3
"""Tests for convert.py - Tana JSON to Markdown/TanaPaste conversion."""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest

from convert import NodeStore, attach_supertag_property, export_node_as_tanapaste

TESTDATA_PATH = Path(__file__).parent / "testdata"


@pytest.mark.parametrize(
    "node_id",
    ["r1shM2RHNgCv", "Oh-JrJ73G9iK", "KhlJy8yJ37KN", "MFjacEHVlv36", "Vi0w332Hvh9b"],
)
def test_node_export(node_id):
    """Test that generated TanaPaste for specific nodes match reference files."""
    store = NodeStore.from_file(TESTDATA_PATH / "test_workspace.json")
    attach_supertag_property(store)
    actual = export_node_as_tanapaste(store, store[node_id])
    expected = (TESTDATA_PATH / f"{node_id}.tanapaste").read_text()

    # Check exact equality
    if actual != expected:
        diff = difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile="expected",
            tofile="actual",
            lineterm="",
        )
        print("".join(diff))
        pytest.fail(f"Content does not match for {node_id}")


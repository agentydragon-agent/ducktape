#!/usr/bin/env python3
"""Tests for convert.py - Tana JSON to Markdown/TanaPaste conversion."""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest
from convert import NodeStore, attach_supertag_property, export_node_as_tanapaste

TESTDATA_PATH = Path(__file__).parent / "testdata"


def get_test_node_ids():
    """Get all node IDs from .tanapaste files in testdata."""
    tanapaste_files = list(TESTDATA_PATH.glob("*.tanapaste"))
    return [f.stem for f in tanapaste_files]


@pytest.mark.parametrize("node_id", get_test_node_ids())
def test_node_export(node_id):
    """Test that generated TanaPaste for specific nodes match reference files."""
    store = NodeStore.from_file(TESTDATA_PATH / "test_workspace.json")
    attach_supertag_property(store)
    actual = export_node_as_tanapaste(store, store[node_id])
    expected = (TESTDATA_PATH / f"{node_id}.tanapaste").read_text()

    # Check exact equality
    if actual != expected:
        # Use ndiff for word-level changes with color-like output
        diff = difflib.ndiff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
        )
        print("".join(diff))
        pytest.fail(f"Content does not match for {node_id}")


@pytest.mark.parametrize(
    "node_id",
    [
        "BYSeNY-L_Yth",
        "5PumeU26_4fo",
        "Oh-JrJ73G9iK",
        "2Ap-6LC3fVuq",
        "6aoZJeWmOXcl",
        "hiHpuPTowhDs",
        "KhlJy8yJ37KN",
        "LkFZLMTHylYl",
        "r1shM2RHNgCv",
        "u00FQD8V08fy",
        "x2-AdByI7b-a",
        "YbPcBamWZFGV",
    ],
)
def test_node_export_minimal_json(node_id):
    """Test that generated TanaPaste from minimal JSON files match reference files."""
    # Load from the minimal JSON file instead of full workspace
    store = NodeStore.from_file(TESTDATA_PATH / f"{node_id}.json")
    attach_supertag_property(store)
    actual = export_node_as_tanapaste(store, store[node_id])
    expected = (TESTDATA_PATH / f"{node_id}.tanapaste").read_text()

    # Check exact equality
    if actual != expected:
        # Use ndiff for word-level changes with color-like output
        diff = difflib.ndiff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
        )
        print("".join(diff))
        pytest.fail(f"Content does not match for {node_id} using minimal JSON")

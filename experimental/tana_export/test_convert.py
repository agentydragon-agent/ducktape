#!/usr/bin/env python3
"""Tests for convert.py - Tana JSON to Markdown/TanaPaste conversion."""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest
from convert import NodeStore, attach_supertag_property, export_node_as_tanapaste

TESTDATA_PATH = Path(__file__).parent / "testdata"


@pytest.fixture
def test_workspace_path():
    """Path to the test workspace JSON file."""
    return TESTDATA_PATH / "test_workspace.json"


@pytest.fixture
def test_workspace_node_tanapaste():
    """Path to the reference TanaPaste export of the workspace node."""
    return TESTDATA_PATH / "test_workspace_node.tanapaste"


@pytest.fixture
def test_tana_workspace_node_tanapaste():
    """Path to the reference TanaPaste export of 'This is a test Tana workspace' node."""
    return TESTDATA_PATH / "r1shM2RHNgCv.tanapaste"


@pytest.fixture
def perfect_eggs_node_tanapaste():
    """Path to the reference TanaPaste export of 'Perfect Eggs' node."""
    return TESTDATA_PATH / "Oh-JrJ73G9iK.tanapaste"


class TestExactFileEquality:
    """Test exact file equality between generated and reference outputs."""

    def test_tanapaste_exact_match(
        self,
        test_workspace_path,
        test_workspace_node_tanapaste,
        tmp_path,
    ):
        """Test that generated TanaPaste exactly matches the reference file."""
        # Load and process the workspace
        store = NodeStore.from_file(test_workspace_path)
        attach_supertag_property(store)

        # Find the "Export Test" node
        export_test_node = None
        for node in store.values():
            if node.name == "Export Test":
                export_test_node = node
                break

        assert export_test_node is not None, "Export Test node not found"

        # Generate TanaPaste output for just the Export Test node
        generated_content = export_node_as_tanapaste(export_test_node, store)

        # Read reference file
        reference_content = test_workspace_node_tanapaste.read_text()

        # Check exact equality
        if generated_content != reference_content:
            # Pretty print the diff
            diff = difflib.unified_diff(
                reference_content.splitlines(keepends=True),
                generated_content.splitlines(keepends=True),
                fromfile="reference (test_workspace_node.tanapaste)",
                tofile="generated",
                lineterm="",
            )
            diff_text = "".join(diff)
            pytest.fail(f"Content does not match. Diff:\n{diff_text}")

    def test_tana_workspace_node_exact_match(
        self,
        test_workspace_path,
        test_tana_workspace_node_tanapaste,
        tmp_path,
    ):
        """Test that generated TanaPaste for 'This is a test Tana workspace' node matches reference."""
        # Load and process the workspace
        store = NodeStore.from_file(test_workspace_path)
        attach_supertag_property(store)

        # Find the specific node by ID
        target_node = None
        for node in store.values():
            if node.id == "r1shM2RHNgCv":
                target_node = node
                break

        assert target_node is not None, "Node r1shM2RHNgCv not found"
        assert target_node.name == "This is a test Tana workspace"

        # Generate TanaPaste output for just this node
        generated_content = export_node_as_tanapaste(target_node, store)

        # Read reference file
        reference_content = test_tana_workspace_node_tanapaste.read_text()

        # Check exact equality
        if generated_content != reference_content:
            # Pretty print the diff
            diff = difflib.unified_diff(
                reference_content.splitlines(keepends=True),
                generated_content.splitlines(keepends=True),
                fromfile="reference (r1shM2RHNgCv.tanapaste)",
                tofile="generated",
                lineterm="",
            )
            diff_text = "".join(diff)
            pytest.fail(f"Content does not match. Diff:\n{diff_text}")

    def test_perfect_eggs_node_exact_match(
        self,
        test_workspace_path,
        perfect_eggs_node_tanapaste,
        tmp_path,
    ):
        """Test that generated TanaPaste for 'Perfect Eggs' node matches reference."""
        # Load and process the workspace
        store = NodeStore.from_file(test_workspace_path)
        attach_supertag_property(store)

        # Find the specific node by ID
        target_node = None
        for node in store.values():
            if node.id == "Oh-JrJ73G9iK":
                target_node = node
                break

        assert target_node is not None, "Node Oh-JrJ73G9iK not found"
        assert target_node.name == "Perfect Eggs"

        # Generate TanaPaste output for just this node
        generated_content = export_node_as_tanapaste(target_node, store)

        # Read reference file
        reference_content = perfect_eggs_node_tanapaste.read_text()

        # Check exact equality
        if generated_content != reference_content:
            # Pretty print the diff
            diff = difflib.unified_diff(
                reference_content.splitlines(keepends=True),
                generated_content.splitlines(keepends=True),
                fromfile="reference (Oh-JrJ73G9iK.tanapaste)",
                tofile="generated",
                lineterm="",
            )
            diff_text = "".join(diff)
            pytest.fail(f"Content does not match. Diff:\n{diff_text}")

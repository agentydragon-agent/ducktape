"""Unit tests for tana2md.py.

These tests validate the most important pieces of behaviour without touching
the full Markdown-generation pipeline.  They construct small in-memory graphs
that mimic the structure of real Tana exports and assert on:

* correct discovery of *Node supertags(s)* attributes and super-tag
  definitions,
* tag-detection logic (`Node.has_tag`),
* outline rendering,
* root detection (`find_roots`), and
* the end-to-end CLI that materialises Markdown files.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import tana2md as t2m
import tanalib as tl
from test_utils import minimal_export, complex_node_export, load_test_graph, create_export_file


# ---------------------------------------------------------------------------
# unit tests
# ---------------------------------------------------------------------------


def test_graph_initialisation():
    g = load_test_graph(minimal_export())

    # super-tag attribute discovered eagerly
    assert "SYS_A13" in g.super_attr_ids

    # tagDef nodes recognised correctly
    assert g.tag_ids["page"] == "PAGE"


def test_node_has_tag():
    g = load_test_graph(minimal_export(super_tag="day"))
    root = g["ROOT"]

    # root node is tagged with `day`
    assert root.has_tag({"DAY"}) is True
    # negative test – other tags not present
    assert root.has_tag({"PAGE"}) is False


def test_outline_rendering():
    g = load_test_graph(minimal_export())
    emitted: set[str] = set()
    lines = t2m.outline(g["ROOT"], emitted)

    # First line contains title and inline #page tag, no separate tuple bullet
    assert lines[0].startswith("- Root")
    assert "#page" in lines[0]
    assert not any("tuple:" in ln for ln in lines[1:])


def test_checkbox_rendering():
    """Test that checkbox fields are rendered using Markdown checkbox format."""
    # Create a simple graph with a checkbox field
    g = tl.Graph({
        "CHECKBOX_FIELD": {
            "id": "CHECKBOX_FIELD",
            "props": {"_docType": "attributeDef", "name": "Show done/not done with a checkbox"},
        },
        # Checked checkbox
        "CHECKBOX_CHECKED": {
            "id": "CHECKBOX_CHECKED",
            "props": {"name": "Yes"},
        },
        "CHECKBOX_TUP_CHECKED": {
            "id": "CHECKBOX_TUP_CHECKED",
            "props": {"_docType": "tuple", "_sourceId": "CHECKBOX_FIELD"},
            "children": ["CHECKBOX_CHECKED"],
        },
        "ITEM_CHECKED": {
            "id": "ITEM_CHECKED",
            "props": {"name": "Item with checked checkbox"},
            "children": ["CHECKBOX_TUP_CHECKED"],
        },
        # Unchecked checkbox
        "CHECKBOX_UNCHECKED": {
            "id": "CHECKBOX_UNCHECKED",
            "props": {"name": "No"},
        },
        "CHECKBOX_TUP_UNCHECKED": {
            "id": "CHECKBOX_TUP_UNCHECKED",
            "props": {"_docType": "tuple", "_sourceId": "CHECKBOX_FIELD"},
            "children": ["CHECKBOX_UNCHECKED"],
        },
        "ITEM_UNCHECKED": {
            "id": "ITEM_UNCHECKED",
            "props": {"name": "Item with unchecked checkbox"},
            "children": ["CHECKBOX_TUP_UNCHECKED"],
        },
        # Empty checkbox (should default to unchecked)
        "CHECKBOX_TUP_EMPTY": {
            "id": "CHECKBOX_TUP_EMPTY",
            "props": {"_docType": "tuple", "_sourceId": "CHECKBOX_FIELD"},
            "children": [],
        },
        "ITEM_EMPTY": {
            "id": "ITEM_EMPTY",
            "props": {"name": "Item with empty checkbox"},
            "children": ["CHECKBOX_TUP_EMPTY"],
        },
    })
    
    # Set up tag_ids to make checkbox field detection work
    g.tag_ids = {"Show done/not done with a checkbox": "CHECKBOX_FIELD"}
    
    # Test with checked item
    emitted = set()
    checked_lines = t2m.outline(g["ITEM_CHECKED"], emitted)
    assert len(checked_lines) >= 2
    assert "- Item with checked checkbox" in checked_lines[0]
    assert "- [x]" in checked_lines[1]
    
    # Test with unchecked item
    emitted = set()
    unchecked_lines = t2m.outline(g["ITEM_UNCHECKED"], emitted)
    assert len(unchecked_lines) >= 2
    assert "- Item with unchecked checkbox" in unchecked_lines[0]
    assert "- [ ]" in unchecked_lines[1]
    
    # Test with empty checkbox (should default to unchecked)
    emitted = set()
    empty_lines = t2m.outline(g["ITEM_EMPTY"], emitted)
    assert len(empty_lines) >= 2
    assert "- Item with empty checkbox" in empty_lines[0]
    assert "- [ ]" in empty_lines[1]


def test_find_roots():
    g = load_test_graph(minimal_export())
    roots = tl.find_roots(g, g.tag_ids)
    assert [n.id for n in roots] == ["ROOT"]


# ---------------------------------------------------------------------------
# integration test (CLI) ----------------------------------------------------
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cli_generates_markdown(tmp_path: Path):
    """Run the full CLI against a minimal export and verify a file appears."""
    export_data = minimal_export(super_tag="page")
    src = create_export_file(tmp_path, export_data)
    dst = tmp_path / "out"

    # Execute the CLI as a subprocess so we exercise argument parsing too.
    result = subprocess.run(
        [sys.executable, str(Path(t2m.__file__).resolve()), str(src), str(dst)],
        capture_output=True,
        text=True,
        check=True,
    )

    # Should write exactly one Markdown file under `out/page/`.
    page_dir = dst / "page"
    files = list(page_dir.glob("*.md"))
    assert (
        len(files) == 1
    ), f"Expected 1 file, found {len(files)}; stderr: {result.stderr}"

    md = files[0].read_text()
    assert "<!-- id: ROOT -->" in md
    assert "#page" in md
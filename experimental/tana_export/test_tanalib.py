"""Unit tests for tanalib.py.

These tests validate the core functionality of the shared library
for processing Tana exports.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import tanalib as tl
from test_utils import minimal_export, complex_node_export, load_test_graph


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_graph_initialization():
    """Test that Graph initializes correctly with the node data."""
    g = tl.Graph({"id1": {"id": "id1", "props": {}}})
    assert "id1" in g
    assert isinstance(g["id1"], tl.Node)


def test_node_properties():
    """Test basic Node properties."""
    data = {"id": "test1", "props": {"name": "Test Node"}, "children": ["child1"]}
    g = tl.Graph({"test1": data, "child1": {"id": "child1", "props": {}}})
    node = g["test1"]
    
    assert node.id == "test1"
    assert node.props.get("name") == "Test Node"
    assert node.children_ids == ["child1"]
    assert len(node.children) == 1
    assert node.children[0].id == "child1"


def test_super_attr_ids_discovery():
    """Test discovery of Node supertags(s) attribute IDs."""
    nodes = {
        "SYS_A13": {
            "id": "SYS_A13",
            "props": {"_docType": "attributeDef", "name": "Node supertags(s)"},
        }
    }
    g = tl.Graph(nodes)
    assert "SYS_A13" in g.super_attr_ids


def test_tag_defs_discovery():
    """Test discovery of tag definitions."""
    nodes = {
        "TAG1": {
            "id": "TAG1",
            "props": {"_docType": "tagDef", "name": "test_tag"},
        }
    }
    g = tl.Graph(nodes)
    assert g.tag_ids["test_tag"] == "TAG1"


def test_node_has_tag():
    """Test detection of tags on nodes."""
    g = load_test_graph(minimal_export(super_tag="day"))
    root = g["ROOT"]
    
    # root node is tagged with `day`
    assert root.has_tag({"DAY"}) is True
    # negative test – other tags not present
    assert root.has_tag({"PAGE"}) is False


def test_node_super_tags():
    """Test retrieval of all super tags on a node."""
    g = load_test_graph(minimal_export(super_tag="day"))
    root = g["ROOT"]
    
    tags = root.super_tags()
    assert "day" in tags
    assert len(tags) == 1


def test_node_title():
    """Test node title extraction with various property sources."""
    nodes = {
        "N1": {"id": "N1", "props": {"name": "Name Prop"}},
        "N2": {"id": "N2", "name": "Name Direct"},
        "N3": {"id": "N3", "props": {"text": "Text Prop"}},
        "N4": {"id": "N4", "props": {"description": "Desc Prop"}},
        "N5": {"id": "N5", "props": {}},
    }
    g = tl.Graph(nodes)
    
    assert g["N1"].title() == "Name Prop"
    assert g["N2"].title() == "Name Direct"
    assert g["N3"].title() == "Text Prop"
    assert g["N4"].title() == "Desc Prop"
    assert g["N5"].title() == ""


def test_find_roots():
    """Test identification of root nodes."""
    g = load_test_graph(minimal_export())
    roots = tl.find_roots(g, g.tag_ids)
    assert len(roots) == 1
    assert roots[0].id == "ROOT"


def test_find_roots_strict():
    """Test identification of root nodes with strict_roots=True."""
    export_data = minimal_export()
    
    # Add an orphan node (no parents, not tagged)
    orphan_node = {
        "id": "ORPHAN",
        "props": {"name": "Orphan Node"},
        "children": [],
    }
    export_data.append(orphan_node)
    
    g = load_test_graph(export_data)
    
    # With strict_roots=False, both tagged and orphaned nodes are roots
    roots_nonstrict = tl.find_roots(g, g.tag_ids, strict_roots=False)
    assert len(roots_nonstrict) == 2
    root_ids = {r.id for r in roots_nonstrict}
    assert "ROOT" in root_ids
    assert "ORPHAN" in root_ids
    
    # With strict_roots=True, only tagged nodes are roots
    roots_strict = tl.find_roots(g, g.tag_ids, strict_roots=True)
    assert len(roots_strict) == 1
    assert roots_strict[0].id == "ROOT"


def test_complex_nodes():
    """Test handling of various complex node types."""
    g = load_test_graph(complex_node_export())
    
    # Test URL node
    url_node = g["URL1"]
    assert url_node.title() == "Link to Tana"
    
    # Test node with attributes
    attr_node = g["ATTR1"]
    assert attr_node.title() == "Node with attributes"
    assert any(child.doc_type == "tuple" for child in attr_node.children)
    
    # Test that system nodes are correctly identified
    table_view = g["TABLE1"]
    assert table_view.is_system is True
    
    query = g["QUERY1"]
    assert query.is_system is True


def test_node_title_with_show_id():
    """Test that node title correctly includes ID when show_id is True."""
    g = tl.Graph({"N1": {"id": "N1", "props": {"name": "Test Node"}}})
    
    assert g["N1"].title(show_id=False) == "Test Node"
    assert g["N1"].title(show_id=True) == "Test Node ‹N1›"


def test_slugify():
    """Test the slugify function."""
    assert tl.slugify("Hello World") == "Hello-World"
    assert tl.slugify("Hello, World!") == "Hello-World"
    assert tl.slugify("Hello   World") == "Hello-World"
    assert tl.slugify("") == "untitled"
    
    # Test length limit
    long_text = "a" * 100
    assert len(tl.slugify(long_text, L=50)) == 50
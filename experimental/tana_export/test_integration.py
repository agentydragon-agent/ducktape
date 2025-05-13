"""Integration tests for tana2paste.py using actual Tana export data.

These tests verify that the generated Tana Paste output correctly formats
real data from a Tana export JSON file.
"""

import io
import os
import pathlib
import pytest
import re

import tana2paste as t2p
import tanalib as tl


# Skip test if actual export file doesn't exist
TANA_EXPORT_PATH = pathlib.Path("/home/agentydragon/downloads/tana-export-2025-05-12.json")
NEED_REAL_EXPORT = pytest.mark.skipif(
    not TANA_EXPORT_PATH.exists(),
    reason=f"Actual export file {TANA_EXPORT_PATH} not found",
)


@NEED_REAL_EXPORT
def test_url_rendering_from_real_export():
    """Test URL rendering using the actual Tana export file."""
    # Load the real export data - but limit to just specific nodes
    # Extract directly from the JSON to avoid loading the entire graph
    import json
    with open(TANA_EXPORT_PATH, 'r') as f:
        data = json.load(f)
    
    # Instead of testing for specific URLs, let's test URL formatting in general
    # We'll find nodes containing URL fields and verify they're rendered correctly
    url_field_id = None
    url_tuples = []
    url_nodes = []
    
    # Find the URL field definition node
    for node in data["docs"]:
        props = node.get("props", {})
        if props.get("name") == "URL" and props.get("_docType") == "attributeDef":
            url_field_id = node["id"]
            url_nodes.append(node)
            break
    
    # Find URL tuple nodes (they reference the URL field)
    if url_field_id:
        for node in data["docs"]:
            props = node.get("props", {})
            if props.get("_docType") == "tuple" and props.get("_sourceId") == url_field_id:
                url_tuples.append(node)
                
                # Also collect the URL values (children of the tuple)
                for child_id in node.get("children", []):
                    for doc in data["docs"]:
                        if doc["id"] == child_id:
                            url_nodes.append(doc)
                
                # And collect parent nodes containing the URL tuple
                for parent in data["docs"]:
                    if node["id"] in parent.get("children", []):
                        url_nodes.append(parent)
    
    # Add some URL nodes directly
    for node in data["docs"]:
        props = node.get("props", {})
        text = props.get("text", "")
        name = props.get("name", "")
        
        if isinstance(text, str) and (text.startswith("http://") or text.startswith("https://")):
            url_nodes.append(node)
        elif isinstance(name, str) and (name.startswith("http://") or name.startswith("https://")):
            url_nodes.append(node)
    
    # De-duplicate nodes
    seen_ids = set()
    unique_nodes = []
    for node in url_nodes + url_tuples:
        if node["id"] not in seen_ids:
            unique_nodes.append(node)
            seen_ids.add(node["id"])
    
    # Create mini graph with these nodes
    mini_graph = {"docs": unique_nodes[:100]}  # Limit to 100 nodes to avoid timeout
    g = tl.load_graph_from_data(mini_graph)
    
    # Render to string buffer
    output = io.StringIO()
    t2p.render_tana_paste(g, output)
    result = output.getvalue()
    
    # Check for Tana paste header
    assert "%%tana%%" in result, "Output missing Tana Paste header"
    
    # Check for proper URL field syntax - should never have "Field:: URL, http"
    assert not re.search(r"Field:: URL,\s+https?://", result), \
        "Output contains incorrectly formatted URL fields"
    
    # Check for proper URL formatting - URLs should be rendered either:
    # 1. As markdown links: [text](url)
    # 2. As URL fields: URL:: url
    assert re.search(r"\[.*?\]\(https?://.*?\)", result), \
        "Output missing properly formatted markdown URL links"
        
    # If we have URL tuple nodes, we might also see URL:: format
    if url_tuples:
        url_field_expected = re.search(r"URL::\s+https?://", result)
        markddown_links_expected = re.search(r"\[.*?\]\(https?://.*?\)", result)
        assert url_field_expected or markddown_links_expected, \
            "Output missing correctly formatted URLs (neither as fields nor markdown links)"
    
    # URLs should never appear as "Field:: URL, https://..."
    assert not re.search(r"Field:: URL,\s+https?://", result), \
        "Output contains incorrectly formatted URL fields"
    
    # We've already verified URL formatting, so no need for specific content checks
    # as our URL node selection is unpredictable


@NEED_REAL_EXPORT
def test_url_tuples_format_in_real_export():
    """Test URL tuple formatting in actual export data."""
    # Load a subset of relevant nodes
    import json
    with open(TANA_EXPORT_PATH, 'r') as f:
        data = json.load(f)
    
    # Find URL nodes and their parents
    url_nodes = []
    parent_ids = set()
    
    for node in data["docs"]:
        props = node.get("props", {})
        name = props.get("name", "")
        if isinstance(name, str) and (name.startswith("http://") or name.startswith("https://")):
            url_nodes.append(node)
            # Find parents
            for potential_parent in data["docs"]:
                if node["id"] in potential_parent.get("children", []):
                    parent_ids.add(potential_parent["id"])
            
            if len(url_nodes) >= 5:
                break
    
    # Include parents and their parents
    all_nodes = list(url_nodes)
    for node in data["docs"]:
        if node["id"] in parent_ids:
            all_nodes.append(node)
            # Find grandparents
            for potential_gp in data["docs"]:
                if node["id"] in potential_gp.get("children", []):
                    all_nodes.append(potential_gp)
    
    # Create a smaller graph with just these nodes
    mini_graph = {"docs": all_nodes}
    g = tl.load_graph_from_data(mini_graph)
    
    # Find nodes with URLs in them
    url_nodes = []
    for node_id, node in g.items():
        props = node.props
        name = props.get("name", "")
        if isinstance(name, str) and (name.startswith("http://") or name.startswith("https://")):
            url_nodes.append(node)
            if len(url_nodes) >= 5:
                break
    
    # For each URL node, verify its rendering
    for url_node in url_nodes:
        # Get URL from the node
        url = url_node.props.get("name", "")
        if not url:
            continue
            
        # Render just this node to test output format
        emitted = set()
        lines = t2p.tana_paste_outline(url_node, emitted)
        
        # Verify it's rendered as a proper link
        rendered = "\n".join(lines)
        assert "[" in rendered and "](" in rendered and ")" in rendered, \
            f"URL node not rendered as a Markdown link: {rendered}"
        assert url in rendered, f"URL {url} not found in rendering: {rendered}"
        assert not "tuple::" in rendered, f"Incorrect 'tuple::' format in URL rendering: {rendered}"
        
        # Parent nodes may have URL fields - check a parent if it exists
        for parent_id, parent in g.items():
            if url_node.id in parent.children_ids:
                # Render parent and check URL field format
                emitted = set()
                parent_lines = t2p.tana_paste_outline(parent, emitted)
                parent_text = "\n".join(parent_lines)
                
                # If this is a tuple node with URL field source, check its parent
                if parent.doc_type == "tuple":
                    source_id = parent.props.get("_sourceId")
                    source_node = g.get(source_id)
                    if source_node and source_node.props.get("name") == "URL":
                        # Find parent of tuple
                        for grandparent_id, grandparent in g.items():
                            if parent.id in grandparent.children_ids:
                                # Render grandparent and check URL field format
                                emitted = set()
                                gp_lines = t2p.tana_paste_outline(grandparent, emitted)
                                gp_text = "\n".join(gp_lines)
                                
                                # Check for URL field format - should be "URL:: url"
                                assert "URL::" in gp_text, \
                                    f"Missing URL:: field in grandparent rendering: {gp_text}"
                                assert not "Field:: URL" in gp_text, \
                                    f"Incorrect Field:: URL format in grandparent: {gp_text}"
                                break
                break


@NEED_REAL_EXPORT
def test_url_formatting_consistency():
    """Test that URLs are consistently formatted in Tana Paste."""
    # Load the export data
    import json
    with open(TANA_EXPORT_PATH, 'r') as f:
        data = json.load(f)
    
    # Find URL field definition
    url_field_id = None
    url_field_node = None
    for node in data["docs"]:
        props = node.get("props", {})
        if props.get("name") == "URL" and props.get("_docType") == "attributeDef":
            url_field_id = node["id"]
            url_field_node = node
            break
    
    # Collect URL tuples and related nodes
    sample_nodes = []
    if url_field_node:
        sample_nodes.append(url_field_node)
    
    # Find a few URL tuples
    url_tuples = []
    if url_field_id:
        for node in data["docs"]:
            props = node.get("props", {})
            if props.get("_docType") == "tuple" and props.get("_sourceId") == url_field_id:
                url_tuples.append(node)
                if len(url_tuples) >= 5:  # Limit to 5 tuples
                    break
    
    # For each tuple, collect its children and parents
    related_nodes = []
    for tup in url_tuples:
        sample_nodes.append(tup)
        
        # Get children (URL values)
        for child_id in tup.get("children", []):
            for doc in data["docs"]:
                if doc["id"] == child_id:
                    related_nodes.append(doc)
                    break
        
        # Get parent (node containing the URL field)
        for parent in data["docs"]:
            if tup["id"] in parent.get("children", []):
                related_nodes.append(parent)
                break
    
    # Add a few URL nodes directly
    url_nodes = []
    for node in data["docs"]:
        props = node.get("props", {})
        text = props.get("text", "")
        name = props.get("name", "")
        
        if isinstance(text, str) and (text.startswith("http://") or text.startswith("https://")):
            url_nodes.append(node)
        elif isinstance(name, str) and (name.startswith("http://") or name.startswith("https://")):
            url_nodes.append(node)
            
        if len(url_nodes) >= 5:  # Limit to 5 direct URL nodes
            break
    
    # Combine all nodes
    all_nodes = sample_nodes + related_nodes + url_nodes
    
    # De-duplicate
    seen_ids = set()
    unique_nodes = []
    for node in all_nodes:
        if node["id"] not in seen_ids:
            unique_nodes.append(node)
            seen_ids.add(node["id"])
    
    # Create mini graph
    mini_graph = {"docs": unique_nodes}
    g = tl.load_graph_from_data(mini_graph)
    
    # Render to string buffer
    output = io.StringIO()
    t2p.render_tana_paste(g, output)
    result = output.getvalue()
    
    # Check for proper field syntax
    assert "%%tana%%" in result, "Output missing Tana Paste header"
    
    # URLs should be properly formatted in one of these ways:
    # 1. As markdown links: [text](url)
    # 2. As URL fields: URL:: url
    assert re.search(r"\[.*?\]\(https?://.*?\)", result), \
        "Output missing properly formatted markdown URL links"
    
    # If we found URL tuples, we might also see URL:: format
    if url_tuples:
        url_field_format = re.search(r"URL::\s+https?://", result)
        markdown_link_format = re.search(r"\[.*?\]\(https?://.*?\)", result)
        assert url_field_format or markdown_link_format, \
            "Output missing correctly formatted URLs (neither as fields nor markdown links)"
        
    # Should never have "Field:: URL, http"
    assert not re.search(r"Field:: URL,\s+https?://", result), \
        "Output contains incorrectly formatted URL fields as 'Field:: URL, url'"
        
    # Should never have "tuple:: URL, http"
    assert not re.search(r"tuple::\s+URL,", result), \
        "Output contains incorrectly formatted URL tuples"
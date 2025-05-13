"""Test utilities for Tana export tests.

This module provides common test functionality for testing Tana export conversions.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Union, Callable

import tanalib as tl


def minimal_export(*, super_tag: str = "page") -> list[dict]:
    """Return a minimal Tana export payload as *list* of node dicts.

    The resulting structure contains:

    * `SYS_A13` – attributeDef *Node supertags(s)*
    * tagDef nodes for the four recognised super-tags
    * a root node titled *Root*, tagged with *super_tag*
    """

    attr_id = "SYS_A13"

    attr_node = {
        "id": attr_id,
        "props": {"_docType": "attributeDef", "name": "Node supertags(s)"},
        "children": [],
    }

    tags = ["day", "page", "issue", "event"]
    tag_nodes = [
        {
            "id": tag.upper(),
            "props": {"_docType": "tagDef", "name": tag},
            "children": [],
        }
        for tag in tags
    ]

    tuple_id = "TUP1"
    root_id = "ROOT"

    tuple_node = {
        "id": tuple_id,
        "props": {"_docType": "tuple", "_sourceId": attr_id},
        "children": [super_tag.upper()],
    }

    root_node = {
        "id": root_id,
        "props": {"name": "Root"},
        "children": [tuple_id],
    }

    return [attr_node] + tag_nodes + [tuple_node, root_node]


def complex_node_export() -> list[dict]:
    """Return a more complex Tana export with various node types."""
    base_export = minimal_export(super_tag="page")
    
    # Add a table view node
    table_view_id = "TABLE1"
    table_view_node = {
        "id": table_view_id,
        "props": {"_docType": "view", "name": "Table View"},
        "children": [],
    }
    
    # Add a supertag definition node
    supertag_def_id = "STAG1"
    supertag_def_node = {
        "id": supertag_def_id,
        "props": {"_docType": "tagDef", "name": "custom_tag"},
        "children": [],
    }
    
    # Add a node with URL link
    url_node_id = "URL1"
    url_node = {
        "id": url_node_id,
        "props": {"name": "Link to Tana", "text": "https://tana.inc/"},
        "children": [],
    }
    
    # Add a saved query node
    query_id = "QUERY1"
    query_node = {
        "id": query_id,
        "props": {"_docType": "search", "name": "All Pages", "description": "Show all pages"},
        "children": [],
    }
    
    # Add a node with attributes and values
    attr_node_id = "ATTR1"
    attr_value_id = "ATTRVAL1"
    
    attr_value_node = {
        "id": attr_value_id,
        "props": {"name": "Value"},
        "children": [],
    }
    
    attr_tuple_id = "ATTRTUP1"
    attr_tuple_node = {
        "id": attr_tuple_id,
        "props": {"_docType": "tuple", "_sourceId": "FIELD1"},
        "children": [attr_value_id],
    }
    
    attr_node = {
        "id": attr_node_id,
        "props": {"name": "Node with attributes"},
        "children": [attr_tuple_id],
    }
    
    field_def_id = "FIELD1"
    field_def_node = {
        "id": field_def_id,
        "props": {"_docType": "attributeDef", "name": "custom_field"},
        "children": [],
    }
    
    # Add a chat node with replies
    chat_node_id = "CHAT1"
    chat_node = {
        "id": chat_node_id,
        "props": {"_docType": "chat", "name": "Sample Chat"},
        "children": [],
    }
    
    # Add chat messages and replies
    chat_msg1_id = "MSG1"
    chat_msg1 = {
        "id": chat_msg1_id,
        "props": {"name": "User question"},
        "children": [],
    }
    
    # Chat replies field definition
    chat_replies_field_id = "CHATFIELD"
    chat_replies_field = {
        "id": chat_replies_field_id,
        "props": {"_docType": "attributeDef", "name": "Chat replies"},
        "children": [],
    }
    
    # Chat replies tuple connecting message to reply
    chat_replies_tuple_id = "REPLYTUPLE"
    chat_replies_tuple = {
        "id": chat_replies_tuple_id,
        "props": {"_docType": "tuple", "_sourceId": chat_replies_field_id},
        "children": ["REPLY1"],
    }
    
    chat_reply_id = "REPLY1"
    chat_reply = {
        "id": chat_reply_id,
        "props": {"name": "AI response"},
        "children": [],
    }
    
    # Add messages as children to the chat
    chat_node["children"].append(chat_msg1_id)
    chat_msg1["children"].append(chat_replies_tuple_id)
    
    # Add all nodes to the export
    additional_nodes = [
        table_view_node,
        supertag_def_node,
        url_node,
        query_node,
        attr_value_node,
        attr_tuple_node,
        attr_node,
        field_def_node,
        chat_node,
        chat_msg1,
        chat_replies_field,
        chat_replies_tuple,
        chat_reply,
    ]
    
    # Add the new nodes as children to the root
    root_node = None
    for node in base_export:
        if node["id"] == "ROOT":
            root_node = node
            break
    
    if root_node:
        # Add references to the complex nodes to the root node
        root_node["children"].extend([
            url_node_id,
            attr_node_id,
            chat_node_id,
        ])
    
    return base_export + additional_nodes


def create_export_file(tmp_path: Path, export_data: List[Dict[str, Any]]) -> Path:
    """Create a temporary Tana export file for testing.
    
    Args:
        tmp_path: pytest temporary directory
        export_data: List of node dictionaries to include in the export
        
    Returns:
        Path to the created export file
    """
    export_file = tmp_path / "export.json"
    export_file.write_text(json.dumps({"docs": export_data}))
    return export_file


def render_to_string(render_func: Callable, *args, **kwargs) -> str:
    """Capture output from a render function to a string.
    
    Args:
        render_func: Function that writes to an output stream
        *args: Positional arguments to pass to render_func
        **kwargs: Keyword arguments to pass to render_func
        
    Returns:
        String containing the captured output
    """
    output = io.StringIO()
    render_func(*args, output, **kwargs)
    return output.getvalue()


def load_test_graph(export_data: List[Dict[str, Any]]) -> tl.Graph:
    """Create a Graph from test export data.
    
    Args:
        export_data: List of node dictionaries to include in the export
        
    Returns:
        Graph object representing the test export
    """
    return tl.load_graph_from_data({"docs": export_data})
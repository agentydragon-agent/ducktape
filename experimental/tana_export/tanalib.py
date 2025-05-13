"""tanalib.py — shared library for processing Tana exports

This library provides common functionality for working with Tana exports,
including data structures for representing the Tana graph and helpers for 
traversing and analyzing nodes.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Set

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_DEPTH = 100
TAG_RE = re.compile(r"<[^>]*>")
INLINE_REF_RE = re.compile(r'<span[^>]+data-inlineref-node="([^"]+)"[^>]*></span>')
SYSTEM_TYPES = {
    "tagDef",
    "attributeDef",
    "field-definition",
    "workspace",
    "view",
    "viewDef",  # observed in real exports
    "search",   # add search to system types
}

# Super-tags that mark roots / buckets
ROOT_TAGS: tuple[str, ...] = ("day", "page", "issue", "event")


# ─── Node / Graph ────────────────────────────────────────────────────
@dataclass
class Node:
    id: str
    raw: Dict[str, Any]
    graph: "Graph"

    @property
    def props(self) -> Dict[str, Any]:
        return self.raw.get("props", {})

    @property
    def doc_type(self) -> str | None:
        return self.props.get("_docType")

    @property
    def children_ids(self) -> List[str]:
        return self.raw.get("children", [])

    @property
    def children(self) -> List["Node"]:
        return [self.graph[c] for c in self.children_ids if c in self.graph]

    def title(self, *, show_id: bool = False) -> str:
        raw = (
            self.props.get("name")
            or self.raw.get("name")
            or self.props.get("text")
            or self.props.get("description")
            or ""
        )

        def repl(m):
            rid = m.group(1)
            return f"[[{self.graph[rid].title(show_id=show_id) or rid}|{rid}]]"

        txt = INLINE_REF_RE.sub(repl, raw)
        txt = TAG_RE.sub("", txt).replace("\\n", " ").strip()
        return f"{txt} ‹{self.id}›" if show_id and txt else txt

    def debug(self, msg: str, *, debug_node: str | None = None):
        if debug_node and self.id == debug_node:
            logging.debug(f"[{self.id}] {msg}")

    @property
    def is_system(self) -> bool:
        return self.id.startswith("SYS_") or self.doc_type in SYSTEM_TYPES

    # ------------------------------------------------------------------
    # Tag helpers placed into Node for easier use
    # ------------------------------------------------------------------

    def _tuple_has_tag(self, t: "Node", tag_set: set[str]) -> bool:
        """Return True if *t* (tuple) references any tag in *tag_set* and is
        connected to the *Node supertags(s)* attribute."""

        if t.doc_type != "tuple":
            return False

        if not any(cid in tag_set for cid in t.children_ids):
            return False

        attr_ids = self.graph.super_attr_ids
        if t.props.get("_sourceId") in attr_ids:
            return True
        return any(cid in attr_ids for cid in t.children_ids)

    def has_tag(self, tag_set: set[str]) -> bool:
        """Return True when the node is marked with one of *tag_set*."""

        # direct tuple children
        for t in self.children:
            if self._tuple_has_tag(t, tag_set):
                return True

        # meta tuples
        mid = self.props.get("_metaNodeId")
        if mid and mid in self.graph:
            meta = self.graph[mid]
            for t in meta.children:
                if self._tuple_has_tag(t, tag_set):
                    return True
        return False

    # ------------------------------------------------------------------
    def super_tags(self) -> List[str]:
        """Return list of *all* tag names applied as super-tags on this node."""

        tag_names: list[str] = []
        for name, tid in self.graph.tag_ids.items():
            if self.has_tag({tid}):
                tag_names.append(name)
        return tag_names
        
    # ------------------------------------------------------------------
    def all_tags(self) -> List[str]:
        """Return all tag names (not just super-tags) applied to this node.
        
        This includes:
        1. Super-tags that determine the node type
        2. Regular tags applied directly to the node 
        3. Tags coming from tuples
        """
        # Get super-tags first
        tags = set(self.super_tags())
        
        # Look for tuple nodes that might contain tags
        for child in self.children:
            if child.doc_type == "tuple":
                # Each child of a tuple might be a tag
                for tag_id in child.children_ids:
                    if tag_id in self.graph and tag_id in self.graph.tag_name_by_id:
                        tags.add(self.graph.tag_name_by_id[tag_id])
        
        # Check meta node for additional tags
        mid = self.props.get("_metaNodeId")
        if mid and mid in self.graph:
            meta = self.graph[mid]
            for meta_child in meta.children:
                if meta_child.doc_type == "tuple":
                    # Each child of a tuple in meta might be a tag
                    for tag_id in meta_child.children_ids:
                        if tag_id in self.graph and tag_id in self.graph.tag_name_by_id:
                            tags.add(self.graph.tag_name_by_id[tag_id])
                            
        return sorted(list(tags))

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def tuple_line(self, *, show_id: bool = False) -> str:
        src = self.props.get("_sourceId")
        tag_name = next((k for k, v in self.graph.tag_ids.items() if v == src), "tuple")
        # Special handling for URL field to ensure correct casing
        if tag_name.lower() == "url":
            tag_name = "URL"
        
        # Handle checkbox fields specially
        is_checkbox = any(kw in tag_name.lower() for kw in ["checkbox", "done", "completed", "to-do", "todo"])
        
        if is_checkbox:
            # For checkbox fields, use Markdown checkbox format
            vals = [c.title() for c in self.children if c.title()]
            if not vals:
                # Default to unchecked if no values
                return "[ ]"
            
            for val in vals:
                # Check if any value indicates a checked state
                if val.lower() in ["yes", "true", "done", "checked"]:
                    return "[x]" if not show_id else f"[x] ‹{self.id}›"
            
            # Otherwise, it's unchecked
            return "[ ]" if not show_id else f"[ ] ‹{self.id}›"
        else:
            # Regular field formatting
            vals = [c.title() for c in self.children if c.title()]
            # Use double colon for Tana Paste format with space (not comma) separator
            txt = f"{tag_name}:: {' '.join(vals)}" if vals else f"{tag_name}::"
            return f"{txt} ‹{self.id}›" if show_id else txt

    def meta_lines(self, *, show_id: bool = False) -> List[str]:
        mid = self.props.get("_metaNodeId")
        if not mid or mid not in self.graph:
            return []

        meta = self.graph[mid]
        all_tag_ids = set(self.graph.tag_ids.values())
        out: list[str] = []
        for c in meta.children:
            if c.doc_type == "tuple":
                # skip tuples that merely assign super-tags (they'll be shown inline)
                if self._tuple_has_tag(c, all_tag_ids):
                    continue
                out.append(c.tuple_line(show_id=show_id))
            else:
                t = c.title()
                if t:
                    out.append(t)
        return out


class Graph(dict):
    """Graph mapping node id → Node with extra lookup helpers."""

    def __init__(self, mapping: Dict[str, Any]):
        super().__init__({k: Node(k, v, self) for k, v in mapping.items()})

        # Discover helper sets/maps eagerly so downstream helpers stay simple.
        self.super_attr_ids: set[str] = self._discover_super_attr_ids()
        self.tag_ids: Dict[str, str] = self._discover_tag_defs()

    # ------------------------------------------------------------------
    def _discover_super_attr_ids(self) -> set[str]:
        ids = {
            n.id
            for n in self.values()
            if n.doc_type == "attributeDef"
            and str(n.props.get("name", "")).lower().startswith("node supertags")
        }
        return ids or {"SYS_A13"}

    # ------------------------------------------------------------------
    def _discover_tag_defs(self) -> Dict[str, str]:
        tag_map = {
            str(n.props.get("name", "")).lower(): n.id
            for n in self.values()
            if n.doc_type == "tagDef"
        }
        self.tag_name_by_id = {v: k for k, v in tag_map.items()}
        return tag_map


# ─── load helpers ────────────────────────────────────────────────────
def load_graph_from_file(path: str) -> Graph:
    """Load a Tana export JSON file and create a Graph object.
    
    Args:
        path: Path to the JSON file to load.
        
    Returns:
        A Graph object representing the Tana export.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return load_graph_from_data(data)


def load_graph_from_json_string(json_string: str) -> Graph:
    """Load a Tana export from a JSON string and create a Graph object.
    
    Args:
        json_string: JSON string containing the Tana export.
        
    Returns:
        A Graph object representing the Tana export.
    """
    data = json.loads(json_string)
    return load_graph_from_data(data)


def load_graph_from_data(data: Dict[str, Any]) -> Graph:
    """Load a Tana export from a parsed JSON data structure.
    
    Args:
        data: Dictionary containing the Tana export data.
        
    Returns:
        A Graph object representing the Tana export.
    """
    if "docs" not in data:
        raise ValueError("Invalid Tana export: missing 'docs' field")
        
    docs = data["docs"]
    nodes = {node["id"]: node for node in docs}
    return Graph(nodes)


# For backward compatibility
def detect_nodes(data: Any) -> Dict[str, Any]:
    """Legacy function for backward compatibility."""
    return {n["id"]: n for n in data["docs"]}


def load_graph(path: str) -> Graph:
    """Legacy function for backward compatibility."""
    return load_graph_from_file(path)


# ─── root detection ─────────────────────────────────────────────────
def find_roots(
    g: Graph,
    tag_ids: Dict[str, str],
    *,
    strict_roots: bool = False,
    debug_node: str | None = None,
) -> List[Node]:
    parents = {cid for n in g.values() for cid in n.children_ids}
    tag_set = {tag_ids[name] for name in ROOT_TAGS if name in tag_ids}
    roots = []
    for n in g.values():
        title = n.title()
        if n.is_system or n.doc_type == "search":
            continue
        if not title or title.lower() in {"default", "calendar"}:
            continue
        tagged = n.has_tag(tag_set)
        orphan = n.id not in parents
        root = (strict_roots and tagged) or ((not strict_roots) and (orphan or tagged))
        if root:
            n.debug(f"ROOT {orphan=} {tagged=}", debug_node=debug_node)
            roots.append(n)
        else:
            n.debug(f"skip {orphan=} {tagged=}", debug_node=debug_node)
    return roots


def slugify(t: str, L: int = 50) -> str:
    return (re.sub(r"[^A-Za-z0-9\-]+", "-", t).strip("-") or "untitled")[:L]


def order_nodes_by_hierarchy(g: Graph, nodes: List[Node]) -> List[Node]:
    """Order nodes so that parent nodes come before their children.
    
    This ensures that when rendering miscellaneous nodes, we process higher-level
    nodes first, preventing their children from being rendered separately.
    """
    # Build a parent-child relationship map
    parent_map = {}
    
    # First identify all parent-child relationships in the graph
    for node in g.values():
        for child_id in node.children_ids:
            if child_id in g:
                parent_map[child_id] = parent_map.get(child_id, []) + [node.id]
    
    # Cache for storing computed depths to avoid redundant calculations
    depth_cache = {}
    
    # Define node depth (distance from a root)
    def get_node_depth(node_id):
        # Return cached result if available
        if node_id in depth_cache:
            return depth_cache[node_id]
        
        # Mark as being computed (to detect cycles)
        depth_cache[node_id] = float('inf')
        
        # If node has no parents, it's at depth 0
        if node_id not in parent_map or not parent_map[node_id]:
            depth = 0
        else:
            # Otherwise, its depth is 1 + min depth of its parents
            # Skip parents with infinite depth (cycles)
            parent_depths = [get_node_depth(parent) for parent in parent_map[node_id]]
            valid_depths = [d for d in parent_depths if d != float('inf')]
            
            if valid_depths:
                depth = 1 + min(valid_depths)
            else:
                depth = 0  # If all parents form cycles, treat as root
        
        # Store computed depth in cache
        depth_cache[node_id] = depth
        return depth
    
    # Sort nodes by depth - nodes with smaller depth (closer to root) come first
    return sorted(nodes, key=lambda node: get_node_depth(node.id))
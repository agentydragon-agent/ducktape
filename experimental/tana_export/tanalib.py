"""tanalib.py — shared library for processing Tana exports

This library provides common functionality for working with Tana exports,
including data structures for representing the Tana graph and helpers for 
traversing and analyzing nodes.
"""

from __future__ import annotations

import json
import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, List

from pydantic import BaseModel

# type == tagDef:
{
  "id": "SYS_T01",
  "props": {
    "created": 1746991012346,
    "name": "supertag",
    "description": "The Core supertag.  The supertag for the supertag nodes",
    "_docType": "tagDef",
    "_ownerId": "SYS_T00",
    "_metaNodeId": "SYS_T01_META"
  }
}


class Node(BaseModel):
    id: str
    created: int # TODO: parse; in props
    description: str | None = None # not always present; in props


class TagDefinition(Node):
    """Node that has props._docType = tagDef."""



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

# Name of the Trash node
TRASH_NODE_NAME = "Deleted Nodes"


# ─── Node / Graph ────────────────────────────────────────────────────

@contextmanager
def cycle_protection(visiting_stack: set[str], node_id: str):
    """Context manager for tracking node visiting to prevent cycles.

    Args:
        visiting_stack: Set of node IDs currently being visited
        node_id: ID of the current node to track

    Yields:
        Boolean indicating if the node is already being visited (cycle detected)
    """
    cycle_detected = node_id in visiting_stack

    # Add node to visiting stack if not already there
    if not cycle_detected:
        visiting_stack.add(node_id)

    try:
        yield cycle_detected
    finally:
        # Only remove if we added it
        if not cycle_detected:
            visiting_stack.remove(node_id)

@dataclass
class Node:
    id: str
    raw: Dict[str, Any]
    graph: Graph

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

    def is_tuple(self) -> bool:
        return self.doc_type == "tuple"

    @property
    def meta_node_id(self) -> str | None:
        return self.props.get("_metaNodeId")

    def title(self, *, show_id: bool = False, visiting_stack: set[str] | None = None) -> str:
        raw = (
            self.props.get("name")
            or self.raw.get("name")
            or self.props.get("text")
            or self.props.get("description")
            or ""
        )

        # Initialize visiting stack for recursive calls to detect cycles
        if visiting_stack is None:
            visiting_stack = set()

        # Use context manager for cycle protection
        with cycle_protection(visiting_stack, self.id) as cycle_detected:
            if cycle_detected:
                return f"<<recursive-ref:{self.id}>>"

            def repl(m):
                rid = m.group(1)
                # Only process references to nodes that aren't in the visiting stack
                if rid in self.graph and rid not in visiting_stack:
                    x = f"{self.graph[rid].title(show_id=show_id, visiting_stack=visiting_stack)}|{rid}"
                else:
                    x = rid
                return f"[[{x}]]"

            txt = INLINE_REF_RE.sub(repl, raw)
            txt = TAG_RE.sub("", txt).replace("\\n", " ").strip()

            return f"{txt} ‹{self.id}›" if show_id and txt else txt

    def debug(self, msg: str, *, debug_node: str | None = None):
        if debug_node and self.id == debug_node:
            logging.debug(f"[{self.id}] {msg}")

    @property
    def is_system(self) -> bool:
        return self.id.startswith("SYS_") or self.doc_type in SYSTEM_TYPES

    @property
    def is_trash(self) -> bool:
        """Return True if this node is the trash node."""
        return (self.props.get("name") == TRASH_NODE_NAME and 
                "_ownerId" in self.props and 
                "description" in self.props and
                "When a node is deleted" in self.props.get("description", ""))

    @property
    def owner_id(self) -> str | None:
        """Return the owner ID of this node if set."""
        return self.props.get("_ownerId")

    # ------------------------------------------------------------------
    # Tag helpers placed into Node for easier use
    # ------------------------------------------------------------------

    def _tuple_has_tag(self, tag_set: set[str]) -> bool:
        """Return True if *t* (tuple) references any tag in *tag_set* and is
        connected to the *Node supertags(s)* attribute."""

        if not self.is_tuple():
            return False

        if not any(cid in tag_set for cid in self.children_ids):
            return False

        attr_ids = self.graph.super_attr_ids
        return (
            self.props.get("_sourceId") in attr_ids or
            any(cid in attr_ids for cid in self.children_ids)
        )

    def has_tag(self, tag_set: set[str]) -> bool:
        """Return True when the node is marked with one of *tag_set*."""
        # direct tuple children
        if any(t._tuple_has_tag(tag_set) for t in self.children):
            return True

        # meta tuples
        mid = self.meta_node_id
        if not mid:
            return False

        return any(t._tuple_has_tag(tag_set) for t in self.graph[mid].children)

    # ------------------------------------------------------------------
    def super_tags(self) -> List[str]:
        """Return list of *all* tag names applied as super-tags on this node."""
        tag_names: list[str] = []
        for name, tid in self.graph.tag_ids.items():
            if self.has_tag({tid}):
                tag_names.append(name)

        return tag_names

    # ------------------------------------------------------------------
    def all_tags(self, visited: set[str] = None) -> List[str]:
        """Return all tag names (not just super-tags) applied to this node.
        
        This includes:
        1. Super-tags that determine the node type
        2. Regular tags applied directly to the node 
        3. Tags coming from tuples
        """
        # Initialize visited set for cycle detection if this is the top-level call
        if visited is None:
            visited = set()

        # Use the context manager for cycle protection
        with cycle_protection(visited, self.id) as cycle_detected:
            if cycle_detected:
                return []

            # Get super-tags first
            tags = set(self.super_tags())

            # Look for tuple nodes that might contain tags
            for child in self.children:
                if not child.is_tuple():
                    continue
                # Each child of a tuple might be a tag
                for tag_id in child.children_ids:
                    if (tag_name := self.graph.tag_name_by_id.get(tag_id)):
                        tags.add(tag_name)

            # Check meta node for additional tags
            if not (mid := self.meta_node_id):
                return []

            for meta_child in self.graph[mid].children:
                if not meta_child.is_tuple():
                    continue
                # Each child of a tuple in meta might be a tag
                for tag_id in meta_child.children_ids:
                    if (tag_name := self.graph.tag_name_by_id.get(tag_id)):
                        tags.add(tag_name)

            return sorted(list(tags))

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def tuple_line(self, *, show_id: bool = False, visiting_stack: set[str] = None) -> str:
        with cycle_protection(visiting_stack, self.id) as cycle_detected:
            # If this node is already being processed in a parent call,
            # we've hit a cycle, so return a placeholder instead of recursing
            if cycle_detected:
                return f"tuple-cycle:{self.id}"

            src = self.props.get("_sourceId")
            tag_name = next((k for k, v in self.graph.tag_ids.items() if v == src), "tuple")

            vals = []
            for c in self.children:
                if c.id in visiting_stack:
                    continue
                if (title := c.title(visiting_stack=visiting_stack.copy())):
                    vals.append(title)

            # Use double colon for Tana Paste format with space (not comma) separator
            txt = ' '.join([f"{tag_name}::", *vals])

            if show_id:
                txt += f" ‹{self.id}›"
            return txt

    def meta_lines(self, *, show_id: bool = False, visiting_stack: set[str] = None) -> List[str]:
        # Initialize visiting stack for recursive calls to detect cycles
        if visiting_stack is None:
            visiting_stack = set()

        # If this node is already being processed in a parent call,
        # we've hit a cycle, so return nothing
        if self.id in visiting_stack:
            return []
            
        # Add this node to the visiting stack
        visiting_stack.add(self.id)
        
        mid = self.meta_node_id
        if not mid or mid not in self.graph:
            visiting_stack.remove(self.id)
            return []

        # Check for meta node cycle
        if mid in visiting_stack:
            visiting_stack.remove(self.id)
            return []
            
        meta = self.graph[mid]
        all_tag_ids = set(self.graph.tag_ids.values())
        out: list[str] = []
        
        # Add meta node to visiting stack to prevent direct cycles
        visiting_stack.add(mid)
        
        for c in meta.children:
            if c.id in visiting_stack:
                continue  # Skip if we've seen this node already
                
            if c.is_tuple():
                # skip tuples that merely assign super-tags (they'll be shown inline)
                if c._tuple_has_tag(all_tag_ids):
                    continue
                out.append(c.tuple_line(show_id=show_id, visiting_stack=visiting_stack.copy()))
            else:
                if c.id not in visiting_stack:
                    t = c.title(visiting_stack=visiting_stack.copy())
                    if t:
                        out.append(t)
        
        # Remove nodes from visiting stack
        visiting_stack.remove(mid)
        visiting_stack.remove(self.id)
        return out


class Graph(dict):
    """Graph mapping node id → Node with extra lookup helpers."""

    def __init__(self, mapping: Dict[str, Any]):
        super().__init__({k: Node(k, v, self) for k, v in mapping.items()})

        # Discover helper sets/maps eagerly so downstream helpers stay simple.
        self.super_attr_ids: set[str] = self._discover_super_attr_ids()
        self.tag_ids: Dict[str, str] = self._discover_tag_defs()
        self.trash_node_id: str | None = self._discover_trash_node()
        
        # Cache for is_in_trash results
        self._is_in_trash_cache: Dict[str, bool] = {}
        
        # Build parent index for faster lookups - maps node ID to list of parent IDs
        self.parent_index: Dict[str, List[str]] = self._build_parent_index()

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
        
    # ------------------------------------------------------------------
    def _discover_trash_node(self) -> str | None:
        """Find the trash node in the graph if it exists."""
        for node in self.values():
            if node.is_trash:
                return node.id
        return None
    
    # ------------------------------------------------------------------
    def _build_parent_index(self) -> Dict[str, List[str]]:
        """Build an index of parent-child relationships for fast lookups."""
        parent_index = {}
        for node_id, node in self.items():
            for child_id in node.children_ids:
                if child_id in self:
                    if child_id not in parent_index:
                        parent_index[child_id] = []
                    parent_index[child_id].append(node_id)
        return parent_index
        
    # ------------------------------------------------------------------
    def is_in_trash(self, node_id: str, visiting_stack: set[str] = None) -> bool:
        """Check if a node is in the trash (owned by trash node or under it in hierarchy)."""
        # Use cached result if available - this avoids recalculation
        if node_id in self._is_in_trash_cache:
            return self._is_in_trash_cache[node_id]
            
        # If no trash node exists, nothing is in trash
        if not self.trash_node_id:
            self._is_in_trash_cache[node_id] = False
            return False
            
        # If node doesn't exist, it's not in trash
        if node_id not in self:
            self._is_in_trash_cache[node_id] = False
            return False
        
        # Initialize visiting stack if this is the top-level call
        if visiting_stack is None:
            visiting_stack = set()
        
        # Use context manager for cycle protection
        with cycle_protection(visiting_stack, node_id) as cycle_detected:
            if cycle_detected:
                # Don't cache cycle results - we just return false for this traversal path
                # This allows detection via other paths if the node is actually in trash
                return False
                
            node = self[node_id]
            
            # Quick checks for direct trash relationships
            
            # 1. Check if node is directly owned by trash node
            if node.owner_id == self.trash_node_id:
                self._is_in_trash_cache[node_id] = True
                return True
                
            # 2. Check if node is a direct child of the trash node
            if self.trash_node_id and node_id in self[self.trash_node_id].children_ids:
                self._is_in_trash_cache[node_id] = True
                return True
                
            # 3. Check if any parent is in trash (recursively)
            # Use the parent index instead of scanning the entire graph
            parents = self.parent_index.get(node_id, [])
            
            for parent_id in parents:
                # Skip if this would create a cycle
                if parent_id in visiting_stack:
                    continue
                    
                # Check each parent - the first one that's in trash means this node is in trash too
                try:
                    if self.is_in_trash(parent_id, visiting_stack):
                        self._is_in_trash_cache[node_id] = True
                        return True
                except RecursionError:
                    # In case we hit Python's recursion limit (unlikely but possible with very deep hierarchies)
                    # We log this and continue with other parents - a truly nested trash item will be found via
                    # another path if it exists
                    logging.debug(f"Recursion limit hit while checking trash for {node_id} via {parent_id}")
                    continue

            # If we get here, the node is not in trash
            self._is_in_trash_cache[node_id] = False
            return False

    @classmethod
    def load_from_file(cls, path: str) -> Self:
        with open(path, "r", encoding="utf-8") as f:
            return self.load_from_data(json.load(f))


    @classmethod
    def load_graph_from_json_string(cls, json_string: str) -> Self:
        return cls.load_graph_from_data(json.loads(json_string))


    @classmethod
    def load_from_data(cls, data: Dict[str, Any]) -> Self:
        docs = data["docs"]
        return Graph({node["id"]: node for node in docs})


# ─── root detection ─────────────────────────────────────────────────
def find_roots(
    g: Graph,
    tag_ids: Dict[str, str],
    *,
    strict_roots: bool = False,
    debug_node: str | None = None,
    batch_size: int = 500,
) -> List[Node]:
    """Find root nodes in the graph based on specified criteria.

    Args:
        g: Graph to search for roots
        tag_ids: Dictionary mapping tag names to tag IDs
        strict_roots: If True, only nodes with root tags are considered roots
        debug_node: Optional node ID to log debug information for
        batch_size: Number of nodes to process in each batch (for progress reporting)

    Returns:
        List of root nodes
    """
    # Collect all child IDs to identify orphans
    parents = {cid for n in g.values() for cid in n.children_ids}

    # Build tag set for root types
    tag_set = {tag_ids[name] for name in ROOT_TAGS if name in tag_ids}

    # Track nodes being processed for progress reporting
    processed = 0
    roots = []

    # Reusable set for cycle detection to avoid repeated allocations
    visited_set = set()

    # Initialize trash cache with direct relationships to improve performance
    if g.trash_node_id and not g._is_in_trash_cache:
        trash_node = g[g.trash_node_id]
        
        # The trash node itself is not in trash
        g._is_in_trash_cache[g.trash_node_id] = False
        
        # Direct children of trash are in trash
        for child_id in trash_node.children_ids:
            if child_id in g:
                g._is_in_trash_cache[child_id] = True
                
        # Nodes owned by trash are in trash
        for node_id, node in g.items():
            if node.owner_id == g.trash_node_id:
                g._is_in_trash_cache[node_id] = True
    
    # Process nodes by batches for more informative progress reporting
    total_nodes = len(g)
    nodes = list(g.values())
    batch_start = 0
    
    while batch_start < total_nodes:
        batch_end = min(batch_start + batch_size, total_nodes)
        batch = nodes[batch_start:batch_end]
        
        # Process this batch of nodes
        for n in batch:
            processed += 1

            # Skip nodes in trash
            if g.is_in_trash(n.id):
                n.debug(f"SKIP (in trash)", debug_node=debug_node)
                continue

            # Basic filtering - system nodes and search nodes are not roots
            if n.is_system or n.doc_type == "search":
                continue

            # Clear visited set before getting title and tags
            visited_set.clear()

            # Get title with cycle detection
            title = n.title(visiting_stack=visited_set.copy())
            if not title or title.lower() in {"default", "calendar"}:
                continue

            # Reset visited set
            visited_set.clear()
            # Check for tags with cycle detection
            tagged = n.has_tag(tag_set)
            orphan = n.id not in parents
            root = (strict_roots and tagged) or ((not strict_roots) and (orphan or tagged))

            if root:
                n.debug(f"ROOT {orphan=} {tagged=}", debug_node=debug_node)
                roots.append(n)
            else:
                n.debug(f"skip {orphan=} {tagged=}", debug_node=debug_node)

        # Show progress for large graphs
        if batch_end % batch_size == 0 or batch_end == total_nodes:
            elapsed_nodes = batch_end
            logging.info(f"Processed {elapsed_nodes}/{total_nodes} nodes when finding roots ({len(roots)} roots found)")

        # Move to the next batch
        batch_start = batch_end

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
    def get_node_depth(node_id, visiting_stack=None):
        # Initialize visiting stack for recursive calls
        if visiting_stack is None:
            visiting_stack = set()
            
        # Return cached result if available
        if node_id in depth_cache:
            return depth_cache[node_id]
        
        # Use the context manager for cycle protection
        with cycle_protection(visiting_stack, node_id) as cycle_detected:
            if cycle_detected:
                return float('inf')  # Return infinity for nodes in a cycle
                
            # If node has no parents, it's at depth 0
            if node_id not in parent_map or not parent_map[node_id]:
                depth = 0
            else:
                # Otherwise, its depth is 1 + min depth of its parents
                parent_depths = []
                for parent in parent_map[node_id]:
                    # Only consider parents not already in the visiting stack
                    if parent not in visiting_stack:
                        parent_depths.append(get_node_depth(parent, visiting_stack))
                
                if parent_depths:
                    valid_depths = [d for d in parent_depths if d != float('inf')]
                    if valid_depths:
                        depth = 1 + min(valid_depths)
                    else:
                        depth = 0  # If all parents form cycles, treat as root
                else:
                    depth = 0  # If all parents are in cycles, treat as root
            
            # Store computed depth in cache
            depth_cache[node_id] = depth
            return depth
    
    # Sort nodes by depth - nodes with smaller depth (closer to root) come first
    # Limit the max depth to avoid potential issues with very deep hierarchies
    MAX_SORT_DEPTH = 100  # Reasonable limit for sorting
    return sorted(nodes, key=lambda node: min(get_node_depth(node.id), MAX_SORT_DEPTH))

#!/usr/bin/env python3
"""
export_node_subset.py - Export a single Tana node and track all touched nodes.

This utility takes a Tana JSON export and a node ID, then:
1. Exports the node in TanaPaste format
2. Tracks all nodes that were accessed during the export
3. Creates a trimmed JSON file containing only the touched nodes
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .convert import _DOC_CLASS, RenderContext, UnknownNode
from .tana_lib import SUPERTAG_KEY_ID, BaseNode, NodeStore, TupleNode
from .tana_lib.supertags import attach_supertag_property
from .tana_lib.types import NodeId

MIN_TUPLE_CHILDREN = 2
PRETTY_PRINT_LIMIT = 10

# Constants from convert.py
_SUPERTAG_KEY_ID = NodeId(SUPERTAG_KEY_ID)


def _is_wrapper(node: BaseNode) -> bool:
    """Nodes that should *not* get their own bullet - just pass through."""
    return node.props.doc_type in {"workspace", "viewDef", "layout"}


class TrackingNodeStore(NodeStore):
    """A NodeStore that tracks which nodes are accessed."""

    def __init__(self, mapping: dict[NodeId, BaseNode]):
        super().__init__(mapping)
        self.accessed_nodes: set[NodeId] = set()
        self.tracking_enabled: bool = True

    def __getitem__(self, k: NodeId) -> BaseNode:
        if self.tracking_enabled:
            self.accessed_nodes.add(k)
        return super().__getitem__(k)

    def get(self, k: NodeId, default=None):
        if k in self and self.tracking_enabled:
            self.accessed_nodes.add(k)
        return super().get(k, default)


def collect_supertag_dependencies(store: NodeStore, node_ids: set[str]) -> set[str]:
    """
    Collect all nodes needed for supertag resolution of the given nodes.

    This includes:
    - Tuple nodes that define supertags for any of the given nodes
    - Tag definition nodes referenced by those tuples
    - Meta nodes that propagate tags
    - Wrapper nodes that propagate tags to children
    """
    dependencies: set[str] = set()
    to_process: set[str] = set(node_ids)
    processed: set[str] = set()

    while to_process:
        current_id = to_process.pop()
        if current_id in processed:
            continue
        processed.add(current_id)

        if current_id not in store:
            continue

        node = store[NodeId(current_id)]

        # Check if this node has a meta_node_id (inherits tags from it)
        if node.props.meta_node_id and node.props.meta_node_id in store:
            dependencies.add(node.props.meta_node_id)
            to_process.add(node.props.meta_node_id)

        # Look for supertag tuples in this node's children
        for child_id in node.children:
            if child_id not in store:
                continue
            child = store[NodeId(child_id)]
            if (
                isinstance(child, TupleNode)
                and len(child.children) >= MIN_TUPLE_CHILDREN
                and child.children[0] == _SUPERTAG_KEY_ID
            ):
                # This tuple assigns supertags
                dependencies.add(child.id)
                dependencies.add(_SUPERTAG_KEY_ID)

                # Add all the tag value nodes
                for tag_id in child.children[1:]:
                    if tag_id in store:
                        dependencies.add(tag_id)
                        tag_node = store[NodeId(tag_id)]
                        if tag_node.props.meta_node_id:
                            dependencies.add(tag_node.props.meta_node_id)
                            to_process.add(tag_node.props.meta_node_id)

        # Check if this node is owned by a wrapper that might propagate tags
        if node.props.owner_id and node.props.owner_id in store:
            owner = store[NodeId(node.props.owner_id)]
            if _is_wrapper(owner):
                dependencies.add(owner.id)
                to_process.add(owner.id)

    return dependencies


class TrackingRenderContext(RenderContext):
    """A RenderContext that ensures node access is tracked."""

    def __init__(self, store: TrackingNodeStore, style: str):
        super().__init__(store, style)
        self.tracking_store = store

    def render_node(self, n: BaseNode):
        # Make sure the node itself is tracked
        self.tracking_store.accessed_nodes.add(n.id)
        yield from super().render_node(n)


def export_node_with_tracking(
    store: TrackingNodeStore,
    node_id: str,
) -> tuple[str, set[NodeId]]:
    """
    Export a single node as TanaPaste and return the export along with touched node IDs.

    Returns:
        tuple: (tanapaste_output, set_of_touched_node_ids)
    """
    # Get the target node
    if node_id not in store:
        raise ValueError(f"Node {node_id} not found in store")

    node = store[NodeId(node_id)]

    # Clear accessed nodes to start fresh
    store.accessed_nodes.clear()

    # Disable tracking during attach_supertag_property since it iterates all nodes
    store.tracking_enabled = False
    attach_supertag_property(store)
    store.tracking_enabled = True

    # Export the node using tracking context
    lines = ["%%tana%%"]
    ctx = TrackingRenderContext(store, "tana")
    lines.extend(ctx.render_node(node))

    tanapaste = "\n".join(lines).rstrip() + "\n\n"

    # Get all accessed nodes from the export
    export_nodes = store.accessed_nodes.copy()

    # Disable tracking while collecting dependencies to avoid cascading
    store.tracking_enabled = False
    supertag_deps = collect_supertag_dependencies(
        store,
        {str(nid) for nid in export_nodes},
    )
    store.tracking_enabled = True

    # Combine both sets
    all_accessed = export_nodes | {NodeId(nid) for nid in supertag_deps}

    # Return the export and all accessed nodes
    return tanapaste, all_accessed


def create_subset_json(
    original_data: dict[str, Any],
    touched_nodes: set[str],
) -> dict[str, Any]:
    """
    Create a subset of the original JSON containing only the touched nodes.

    Args:
        original_data: The full Tana JSON export data
        touched_nodes: Set of node IDs that were accessed during export

    Returns:
        dict: A new JSON structure with only the touched nodes
    """
    # Filter docs to only include touched nodes
    filtered_docs = [doc for doc in original_data["docs"] if doc["id"] in touched_nodes]

    # Create new JSON structure with same format version
    return {
        "formatVersion": original_data.get("formatVersion", 1),
        "docs": filtered_docs,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Export a single Tana node and create a subset JSON with only touched nodes",
    )
    parser.add_argument("json_file", help="Path to Tana JSON export file")
    parser.add_argument("node_id", help="ID of the node to export")
    parser.add_argument(
        "-o",
        "--output-prefix",
        help="Prefix for output files (default: based on input filename and node ID)",
        default=None,
    )
    parser.add_argument(
        "--no-tanapaste",
        action="store_true",
        help="Skip creating the TanaPaste export file",
    )
    parser.add_argument(
        "--no-subset",
        action="store_true",
        help="Skip creating the subset JSON file",
    )

    args = parser.parse_args()

    # Load the original JSON
    json_path = Path(args.json_file)
    with json_path.open(encoding="utf-8") as f:
        original_data = json.load(f)

    # Create tracking store with proper node types

    def _make_node(raw: dict[str, Any]) -> BaseNode:
        return _DOC_CLASS.get(
            raw["props"].get("_docType"),
            UnknownNode,
        ).model_validate(raw)

    tracking_store = TrackingNodeStore(
        {doc["id"]: _make_node(doc) for doc in original_data["docs"]},
    )

    # Export the node with tracking (attach_supertag_property is called inside)
    try:
        tanapaste_output, touched_nodes = export_node_with_tracking(
            tracking_store,
            args.node_id,
        )
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    # Determine output prefix
    if args.output_prefix:
        output_prefix = Path(args.output_prefix)
    else:
        output_prefix = json_path.with_suffix("") / f"node_{args.node_id}"
        output_prefix.parent.mkdir(exist_ok=True)

    # Write TanaPaste export
    if not args.no_tanapaste:
        tanapaste_path = output_prefix.with_suffix(".tanapaste.txt")
        tanapaste_path.write_text(tanapaste_output, encoding="utf-8")
        print(f"✅ TanaPaste export → {tanapaste_path}")

    # Create and write subset JSON
    if not args.no_subset:
        subset_data = create_subset_json(original_data, touched_nodes)
        subset_path = output_prefix.with_suffix(".subset.json")

        with subset_path.open("w", encoding="utf-8") as f:
            json.dump(subset_data, f, indent=2, ensure_ascii=False)

        print(f"✅ Subset JSON → {subset_path}")
        print(f"   Original nodes: {len(original_data['docs'])}")
        print(f"   Subset nodes: {len(subset_data['docs'])} (touched during export)")

    # Print summary of touched nodes
    print(f"\n📊 Export touched {len(touched_nodes)} nodes:")

    # Show first few node names if available
    node_names = []
    for node_id in sorted(touched_nodes)[:PRETTY_PRINT_LIMIT]:
        node = tracking_store.get(node_id)
        if node and node.name:
            node_names.append(f"  - {node.name[:50]}... ({node_id})")
        else:
            node_names.append(f"  - <unnamed> ({node_id})")

    print("\n".join(node_names))
    if len(touched_nodes) > PRETTY_PRINT_LIMIT:
        print(f"  ... and {len(touched_nodes) - PRETTY_PRINT_LIMIT} more nodes")

    return 0


if __name__ == "__main__":
    sys.exit(main())

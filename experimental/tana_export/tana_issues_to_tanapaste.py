#!/usr/bin/env python3
"""
Extract all #issue nodes (where Status != Done/Cancelled) from a Tana export and output TanaPaste to stdout.

Usage: python tana_issues_to_tanapaste.py <input.json>
"""

import sys
from pathlib import Path

from convert import (
    BaseNode,
    NodeStore,
    RenderContext,
    TupleNode,
    attach_supertag_property,
)


def load_tana_export_as_nodestore(input_path: Path) -> NodeStore:
    """Load a Tana export JSON and convert it to a NodeStore."""
    store = NodeStore.from_file(input_path)
    attach_supertag_property(store)
    return store


def get_field_values(node: BaseNode, field_name: str, store: NodeStore):
    """Get all values for a field as a list of strings."""
    for child in node.child_nodes:
        if (
            isinstance(child, TupleNode)
            and len(child.children) >= 2
            and (key_node := store.get(child.children[0]))
            and key_node.name == field_name
        ):
            # Get all value names
            for value_id in child.children[1:]:
                if (value_node := store.get(value_id)) and value_node.name:
                    yield value_node.name


def is_in_deleted_nodes(node: BaseNode, store: NodeStore) -> bool:
    """Check if a node has 'Deleted Nodes' in its ancestor chain."""
    current: BaseNode | None = node
    visited = set()

    while current:
        if current.id in visited:
            break
        visited.add(current.id)

        if current.name and current.name == "Deleted Nodes":
            return True

        # Check parent
        if current.props.owner_id:
            current = store.get(current.props.owner_id)
        else:
            break

    return False


def filter_open_issues(store: NodeStore):
    """Find all nodes with #issue tag where Status is not Done/Cancelled/Shelved."""
    for node_id, node in store.items():
        # Skip if in trash or under "Deleted Nodes"
        if node.is_trash or is_in_deleted_nodes(node, store):
            continue

        # Must have #issue tag
        if "issue" not in node.supertags:  # type: ignore[attr-defined]
            continue

        # Get status values
        status_values = list(get_field_values(node, "Status", store))

        # Skip if no status field
        if not status_values:
            continue

        # Check if Status is Done, Cancelled, or Shelved
        if {status.lower() for status in status_values} & {
            "done",
            "cancelled",
            "shelved",
        }:
            continue

        yield node_id


def main():
    if len(sys.argv) != 2:
        print("Usage: python tana_issues_to_tanapaste.py <input.json>", file=sys.stderr)
        print(
            "\nExtracts all #issue nodes (where Status != Done/Cancelled) and outputs TanaPaste to stdout",
            file=sys.stderr,
        )
        sys.exit(1)

    input_path = Path(sys.argv[1])

    if not input_path.exists():
        print(f"Error: Input file '{input_path}' not found.", file=sys.stderr)
        sys.exit(1)

    # Load and process
    store = load_tana_export_as_nodestore(input_path)
    issue_ids = list(filter_open_issues(store))

    # Export the given issues as a flat TanaPaste document
    lines = ["%%tana%%"]
    ctx = RenderContext(store, "tana")
    for issue_id in issue_ids:
        lines.extend(ctx.render_node(store[issue_id]))
        lines.append("")  # Empty line between issues

    # Output to stdout
    print("\n".join(lines).rstrip())

    # Report to stderr
    print(f"\n# Total nodes: {len(store)}", file=sys.stderr)
    print(f"# Open issues found: {len(issue_ids)}", file=sys.stderr)


if __name__ == "__main__":
    main()

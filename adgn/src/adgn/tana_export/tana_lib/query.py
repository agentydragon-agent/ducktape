"""
Query functions for working with Tana node structures.
"""

from __future__ import annotations

from collections.abc import Iterator

from .models import BaseNode, NodeStore, TupleNode
from .types import NodeId


def get_field_values(
    node: BaseNode,
    field_name: str,
    store: NodeStore,
) -> Iterator[str]:
    """
    Get all values for a field as a list of strings.

    Args:
        node: The node to search for field values
        field_name: The name of the field to look for
        store: The NodeStore containing all nodes

    Yields:
        String values for the specified field
    """
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
    """
    Check if a node has 'Deleted Nodes' in its ancestor chain.

    Args:
        node: The node to check
        store: The NodeStore containing all nodes

    Returns:
        True if the node is under 'Deleted Nodes', False otherwise
    """
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


def get_ancestors(node: BaseNode, store: NodeStore) -> list[BaseNode]:
    """
    Get all ancestors of a node (parents, grandparents, etc).

    Args:
        node: The node to get ancestors for
        store: The NodeStore containing all nodes

    Returns:
        List of ancestor nodes, from immediate parent to root
    """
    ancestors = []
    current = node
    visited = set()

    while current.props.owner_id and current.props.owner_id not in visited:
        visited.add(current.id)
        if parent := store.get(current.props.owner_id):
            ancestors.append(parent)
            current = parent
        else:
            break

    return ancestors


def find_nodes_by_tag(store: NodeStore, tag_name: str) -> Iterator[BaseNode]:
    """
    Find all nodes with a specific supertag.

    Args:
        store: The NodeStore to search
        tag_name: The tag name to search for

    Yields:
        Nodes that have the specified tag
    """
    for node in store.values():
        if store.has_supertag(node.id, tag_name):
            yield node


def get_tuple_value(node: BaseNode, key_id: NodeId) -> BaseNode | None:
    """
    Get the value node for a specific key from a node's tuple children.

    Args:
        node: The node to search in
        key_id: The ID of the key node (e.g., CHECKBOX_KEY_ID)

    Returns:
        The value node if found, None otherwise
    """
    for child in node.child_nodes:
        if isinstance(child, TupleNode) and len(child.child_nodes) >= 2:
            key_node, val_node = child.child_nodes[:2]
            if key_node.id == key_id:
                return val_node
    return None

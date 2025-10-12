"""
Query functions for working with Tana node structures.
"""

from __future__ import annotations

from collections.abc import Iterator

from .constants import MIN_TUPLE_CHILDREN
from .models import BaseNode, NodeStore, TupleNode


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
            and len(child.children) >= MIN_TUPLE_CHILDREN
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

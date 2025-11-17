"""Core query helpers for Tana export logic.

Typed to the minimal node protocol used in production (NodeProto). This avoids
speculative multi-shape inputs and keeps a single rational path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tana.domain.types import NodeId

if TYPE_CHECKING:
    from tana.domain.nodes import BaseNode


def get_tuple_value(node: BaseNode, key: NodeId | str) -> BaseNode | None:
    """Return the first value node from a tuple keyed by `key`.

    Supports two shapes:
    - node is a tuple node: children[0] is the key id, children[1:] are values
    - node is a container: search its child tuple nodes for one where
      tuple.children[0] == key, then return tuple.child_nodes[1]

    Requires that `node` (or the tuple children) are attached to a store to
    resolve child ids into node objects when returning.
    """
    # Normalize for comparison
    key_str = str(key)

    children = list(node.children)

    # Case 1: node itself is a tuple — check its key
    if children:
        first = children[0]
        if str(first) == key_str:
            # Return first value if present and resolvable via store
            store = node._graph
            if store is not None and len(children) >= 2:
                return store.get(children[1])
            return None

    # Case 2: search child tuples under this node
    # We need a store to inspect child tuple keys/values
    store = node._graph
    if store is None:
        return None

    for cid in children:
        try:
            t = store[cid]
        except KeyError:
            continue
        t_children = list(t.children)
        if not t_children:
            continue
        if str(t_children[0]) != key_str:
            continue
        # Found the right tuple: return its first value node if present
        if len(t_children) >= 2:
            return store.get(t_children[1])
    return None

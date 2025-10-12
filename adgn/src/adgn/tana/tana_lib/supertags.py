"""
Supertag handling for Tana nodes.
"""

from __future__ import annotations

from collections import defaultdict

from .constants import MIN_TUPLE_CHILDREN, SUPERTAG_KEY_ID
from .models import BaseNode, NodeStore, TupleNode
from .wrapper_utils import is_wrapper

def attach_supertag_property(store: NodeStore) -> None:
    """
    Attach a 'supertags' property to all nodes in the store.

    This function analyzes the node relationships and attaches a dynamic
    'supertags' property to each BaseNode instance that returns a list
    of supertag names for that node.
    """
    idx: defaultdict[str, list[str]] = defaultdict(list)

    def _add(id, tags):
        for tag in tags:
            if tag and tag not in idx[id]:
                idx[id].append(tag)

    for n in store.values():
        if not (
            isinstance(n, TupleNode)
            and len(n.children) >= MIN_TUPLE_CHILDREN
            and n.props.owner_id
            and (key_node := store.get(n.children[0]))
            and key_node.id == SUPERTAG_KEY_ID
        ):
            continue
        # Handle multi-value tuples - all children after the key are tag values
        for v in n.child_nodes[1:]:
            if v.name:
                idx[n.props.owner_id].append(v.name)

    # NEW: propagate tags via meta-node link
    for n in store.values():
        if n.props.meta_node_id:
            _add(n.id, idx[n.props.meta_node_id])

    # propagate wrapper tags to visible children
    for w in store.values():
        if is_wrapper(w):
            for cid in w.children:
                _add(cid, idx[w.id])

    BaseNode.supertags = property(lambda self: idx[self.id])  # type: ignore[attr-defined]

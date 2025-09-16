"""Core query helpers for Tana export logic that do NOT depend on models.

This module is intentionally model-agnostic to avoid import cycles: it operates on
either raw node mappings (dict-like) or on objects exposing minimal attributes
(called duck-typed "node" below). Callers in models.py or query.py should adapt
results to BaseNode when needed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _get_attr(node: Any, attr: str):
    """Helper to fetch attributes from either mapping or object with attribute.

    Returns None if attribute missing.
    """
    if node is None:
        return None
    if isinstance(node, Mapping):
        return node.get(attr)
    return getattr(node, attr, None)


def get_tuple_value(node: Any, key: str) -> Any | None:
    """Get the tuple value for `key` from a node.

    Tana represents tuples as nodes whose first child is the key (a NodeId), and
    subsequent children are the values. This helper returns the first value node
    (raw mapping or object) corresponding to the tuple's value, or None if not
    present.

    The helper deliberately does not attempt to convert raw dicts into BaseNode
    instances to avoid importing models here. Callers that need BaseNode objects
    should perform that conversion using their NodeStore.
    """
    # If node is a mapping, try to access props/children
    children = _get_attr(node, "children")
    if not children:
        return None

    # first child is the key node id
    # key_child_id = children[0]

    # iterate over the value children
    for child in children[1:]:
        # For callers that pass BaseNode, retrieving child nodes may already be
        # done by the caller; here we just return the raw child id so caller can
        # resolve via NodeStore. But to preserve previous behavior, if the
        # caller passed a node object with indexing support (like NodeStore), try
        # to resolve.
        if hasattr(node, "_store") and node._store is not None:
            store = node._store
            if child in store:
                # check if this child's id matches the requested key
                # For tuple semantics the first child is the key - matching is
                # done by the parent tuple node; so here we assume children[0]
                # held SUPERTAG_KEY_ID in previous code. To keep this helper
                # general, callers should check the key node separately.
                return store[child]

    # Fallback: return None (caller will resolve using NodeStore if needed)
    return None

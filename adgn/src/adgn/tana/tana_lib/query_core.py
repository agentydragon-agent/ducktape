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


def get_tuple_value(node: Any, key: Any) -> Any | None:
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

    children = _get_attr(node, "children") or []

    # Case 1: node itself is a tuple — check its key
    if children:
        first = children[0]
        if str(first) == key_str:
            # Return first value if present and resolvable via store
            if (
                hasattr(node, "_store")
                and node._store is not None
                and len(children) >= 2
            ):
                try:
                    return node._store[children[1]]
                except Exception:
                    return None
            # Without a store, return the raw child id
            return children[1] if len(children) >= 2 else None

    # Case 2: search child tuples under this node
    # We need a store to inspect child tuple keys/values
    store = getattr(node, "_store", None)
    if store is None:
        return None

    for cid in children:
        try:
            t = store[cid]
        except Exception:
            continue
        t_children = getattr(t, "children", None)
        if not t_children:
            continue
        if str(t_children[0]) != key_str:
            continue
        # Found the right tuple: return its first value node if present
        if len(t_children) >= 2:
            try:
                return store[t_children[1]]
            except Exception:
                return None
    return None

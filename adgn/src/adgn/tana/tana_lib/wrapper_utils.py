from __future__ import annotations

from .models import BaseNode

_WRAPPER_DOC_TYPES = frozenset({"workspace", "viewDef", "layout"})


def is_wrapper(node: BaseNode) -> bool:
    """Return True when the node represents a structural wrapper."""
    return node.props.doc_type in _WRAPPER_DOC_TYPES

"""
Type definitions for the Tana library.
"""

from typing import Mapping, NewType, Protocol, Sequence, TypeVar, runtime_checkable

# Type for node IDs to prevent mixing with regular strings
NodeId = NewType("NodeId", str)


T_Node = TypeVar("T_Node")


@runtime_checkable
class NodeProto(Protocol[T_Node]):
    """Minimal node protocol used by query helpers.

    Avoids importing the Pydantic models to keep layering clean.
    """

    children: Sequence[NodeId]
    _store: Mapping[NodeId, T_Node] | None

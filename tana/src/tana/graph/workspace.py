from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any, Iterator

from tana.domain.constants import MIN_TUPLE_CHILDREN, SUPERTAG_KEY_ID
from tana.domain.nodes import BaseNode, DOC_CLASS, TupleNode, UnknownNode
from tana.domain.types import NodeId
from tana.graph.wrappers import is_wrapper


class TanaGraph(Mapping[NodeId, BaseNode]):
    """In-memory graph representing a Tana workspace export."""

    def __init__(self, nodes: Mapping[NodeId, BaseNode]):
        self._nodes: dict[NodeId, BaseNode] = dict(nodes)
        self._supertag_index: dict[NodeId, list[str]] = {}
        for node in self._nodes.values():
            object.__setattr__(node, "_graph", self)
        self._build_supertag_index()

    # Mapping interface -----------------------------------------------------
    def __getitem__(self, node_id: NodeId) -> BaseNode:
        return self._nodes[node_id]

    def __iter__(self) -> Iterator[NodeId]:
        return iter(self._nodes)

    def __len__(self) -> int:
        return len(self._nodes)

    # Convenience helpers ---------------------------------------------------
    def get(self, node_id: NodeId, default: BaseNode | None = None) -> BaseNode | None:
        return self._nodes.get(node_id, default)

    def values(self) -> Iterable[BaseNode]:
        return self._nodes.values()

    def items(self) -> Iterable[tuple[NodeId, BaseNode]]:
        return self._nodes.items()

    def get_supertags(self, node_id: NodeId) -> list[str]:
        return self._supertag_index.get(node_id, [])

    def has_supertag(self, node_id: NodeId, tag: str) -> bool:
        return tag in self._supertag_index.get(node_id, [])

    # Construction ----------------------------------------------------------
    @classmethod
    def from_documents(cls, documents: Iterable[dict[str, Any]]) -> "TanaGraph":
        """Build a graph from raw JSON documents."""

        def _make_node(raw: dict[str, Any]) -> BaseNode:
            doc_type = raw.get("props", {}).get("_docType")
            node_model = DOC_CLASS.get(doc_type, UnknownNode)
            return node_model.model_validate(raw)  # type: ignore[return-value]

        mapping = {NodeId(str(doc["id"])): _make_node(doc) for doc in documents}
        return cls(mapping)

    # Internal --------------------------------------------------------------
    def _build_supertag_index(self) -> None:
        idx: defaultdict[NodeId, list[str]] = defaultdict(list)

        def _add(node_id: NodeId, tags: list[str]) -> None:
            for tag in tags:
                if tag and tag not in idx[node_id]:
                    idx[node_id].append(tag)

        for node in self._nodes.values():
            if not (
                isinstance(node, TupleNode)
                and len(node.children) >= MIN_TUPLE_CHILDREN
                and node.props.owner_id
                and (key_node := self.get(node.children[0]))
                and key_node.id == SUPERTAG_KEY_ID
            ):
                continue
            for value_node in node.child_nodes[1:]:
                if value_node.name:
                    idx[node.props.owner_id].append(value_node.name)

        for node in self._nodes.values():
            if node.props.meta_node_id:
                _add(node.id, list(idx[node.props.meta_node_id]))

        for wrapper in self._nodes.values():
            if is_wrapper(wrapper):
                for child_id in wrapper.children:
                    _add(child_id, list(idx[wrapper.id]))

        self._supertag_index = dict(idx)


__all__ = ["TanaGraph"]

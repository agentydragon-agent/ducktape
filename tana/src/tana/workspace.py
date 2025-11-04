from __future__ import annotations

from pathlib import Path

from collections.abc import Iterable

from tana.domain.nodes import BaseNode
from tana.domain.types import NodeId
from tana.graph.workspace import TanaGraph
from tana.io.json import load_workspace
from tana.services.search import SearchService


class Workspace:
    """High-level facade around a TanaGraph."""

    def __init__(self, graph: TanaGraph) -> None:
        self.graph = graph
        self._search = SearchService(graph)

    @classmethod
    def load(cls, path: Path | str) -> Workspace:
        graph = load_workspace(Path(path))
        return cls(graph)

    def node(self, node_id: NodeId) -> BaseNode:
        return self.graph[node_id]

    def export_tanapaste(self, node_id: NodeId) -> str:
        from tana.export.convert import export_node_as_tanapaste

        return export_node_as_tanapaste(self.graph, self.node(node_id))

    def materialize_search(self, node_id: NodeId) -> list[NodeId]:
        node = self.node(node_id)
        return self._search.materialize(node)

    def compare_search_results(self, node_id: NodeId) -> dict[str, Iterable[NodeId]]:
        node = self.node(node_id)
        return self._search.compare_results(node)

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from tana.domain.nodes import BaseNode
from tana.domain.types import NodeId
from tana.graph.workspace import TanaGraph
from tana.io.json import load_workspace
from tana.query.search.materializer import compare_search_results, materialize_search


class Workspace:
    """High-level facade around a TanaGraph."""

    def __init__(self, graph: TanaGraph) -> None:
        self.graph = graph

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
        return materialize_search(self.graph, self.node(node_id))

    def compare_search_results(self, node_id: NodeId) -> dict[str, Iterable[NodeId]]:
        return compare_search_results(self.graph, self.node(node_id))

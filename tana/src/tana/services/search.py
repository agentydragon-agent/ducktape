from __future__ import annotations

from typing import Iterable

from tana.domain.nodes import BaseNode
from tana.domain.types import NodeId
from tana.graph.workspace import TanaGraph
from tana.query.search.evaluator import SearchEvaluator
from tana.query.search.materializer import compare_search_results, materialize_search
from tana.query.search.parser import parse_search_expression


class SearchService:
    """High-level API for parsing and executing search nodes."""

    def __init__(self, graph: TanaGraph) -> None:
        self._graph = graph

    def get_node(self, node_id: NodeId) -> BaseNode:
        return self._graph[node_id]

    def parse_expression(self, node: BaseNode):
        return parse_search_expression(self._graph, node)

    def materialize(self, node: BaseNode) -> list[NodeId]:
        return materialize_search(self._graph, node)

    def compare_results(self, node: BaseNode) -> dict[str, Iterable[NodeId]]:
        return compare_search_results(self._graph, node)

    def evaluator(self, *, parent_node: BaseNode | None = None) -> SearchEvaluator:
        return SearchEvaluator(self._graph, parent_node=parent_node)

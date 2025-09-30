"""
Materializer for Tana search nodes.

This module provides functionality to re-execute searches from Tana exports
and materialize their results.
"""

from __future__ import annotations

from .models import BaseNode, NodeStore
from .search_evaluator import SearchEvaluator
from .search_parser import parse_search_expression
from .types import NodeId


def materialize_search(store: NodeStore, search_node: BaseNode) -> list[NodeId]:
    """
    Materialize a search node by executing its search expression.

    Args:
        store: The NodeStore containing all nodes
        search_node: The search node to materialize

    Returns:
        List of node IDs matching the search
    """
    # Parse the search expression
    expression = parse_search_expression(store, search_node)
    if not expression:
        return []

    # Get search context if specified
    context = None
    if search_node.props.search_context_node:
        context = store.get(NodeId(search_node.props.search_context_node))

    # Get parent node for PARENT resolution
    parent_node = None
    if search_node.props.owner_id:
        parent_node = store.get(search_node.props.owner_id)

    # Create evaluator and execute search
    evaluator = SearchEvaluator(store, parent_node=parent_node)
    results = evaluator.evaluate(expression, context)

    # Collect and return node IDs
    return [node.id for node in results]


def compare_search_results(
    store: NodeStore,
    search_node: BaseNode,
) -> dict[str, list[NodeId]]:
    """
    Compare stored search results with re-executed results.

    Args:
        store: The NodeStore
        search_node: The search node to compare

    Returns:
        Dictionary with 'stored', 'materialized', 'missing', and 'extra' results
    """
    # Get stored results
    stored_results = search_node.children

    # Get materialized results
    materialized_results = materialize_search(store, search_node)

    # Convert to sets for comparison
    stored_set = set(stored_results)
    materialized_set = set(materialized_results)

    return {
        "stored": stored_results,
        "materialized": materialized_results,
        "missing": list(stored_set - materialized_set),
        "extra": list(materialized_set - stored_set),
    }

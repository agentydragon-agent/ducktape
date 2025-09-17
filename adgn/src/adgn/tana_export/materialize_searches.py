#!/usr/bin/env python3
"""
CLI tool to materialize search nodes from Tana JSON exports.

Usage: python materialize_searches.py input.json [--search-id SEARCH_ID] [--all]
"""

import argparse
from pathlib import Path
import sys

from .tana_lib import NodeStore
from .tana_lib.search_materializer import compare_search_results
from .tana_lib.search_parser import parse_search_expression
from .tana_lib.types import NodeId

PRETTY_PRINT_LIMIT = 10


def find_all_searches(store: NodeStore) -> list[str]:
    """Find all search nodes in the store."""
    return [node.id for node in store.values() if node.props.doc_type == "search"]


def print_search_info(store: NodeStore, search_id: str) -> None:
    """Print information about a search node."""
    search_node = store.get(NodeId(search_id))
    if not search_node:
        print(f"Search node {search_id} not found")
        return

    print(f"\nSearch: {search_node.name or search_id}")
    print(f"ID: {search_id}")

    # Parse and print expression
    expression = parse_search_expression(store, search_node)
    if expression:
        print(f"Expression: {expression}")
    else:
        print("Expression: <none>")

    # Compare results
    comparison = compare_search_results(store, search_node)

    print(f"\nStored results: {len(comparison['stored'])}")
    print(f"Materialized results: {len(comparison['materialized'])}")

    if comparison["missing"]:
        print(f"\nMissing from materialized ({len(comparison['missing'])}):")
        for node_id in comparison["missing"][:PRETTY_PRINT_LIMIT]:  # Show first N
            node = store.get(NodeId(node_id))
            name = node.name if node else "<unknown>"
            print(f"  - {name} ({node_id})")
        if len(comparison["missing"]) > PRETTY_PRINT_LIMIT:
            print(f"  ... and {len(comparison['missing']) - PRETTY_PRINT_LIMIT} more")

    if comparison["extra"]:
        print(f"\nExtra in materialized ({len(comparison['extra'])}):")
        for node_id in comparison["extra"][:PRETTY_PRINT_LIMIT]:  # Show first N
            node = store.get(NodeId(node_id))
            name = node.name if node else "<unknown>"
            print(f"  - {name} ({node_id})")
        if len(comparison["extra"]) > PRETTY_PRINT_LIMIT:
            print(f"  ... and {len(comparison['extra']) - PRETTY_PRINT_LIMIT} more")

    if not comparison["missing"] and not comparison["extra"]:
        print("\n✅ Stored and materialized results match!")


def main():
    parser = argparse.ArgumentParser(
        description="Materialize search nodes from Tana JSON exports",
    )
    parser.add_argument("input", help="Tana JSON export file")
    parser.add_argument(
        "--search-id",
        help="Specific search node ID to materialize",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all search nodes",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all search nodes",
    )

    args = parser.parse_args()

    # Load the NodeStore
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file '{input_path}' not found.", file=sys.stderr)
        sys.exit(1)

    store = NodeStore.from_file(input_path)

    # Find all searches
    all_searches = find_all_searches(store)

    if args.list:
        print(f"Found {len(all_searches)} search nodes:")
        for search_id in all_searches:
            search_node = store.get(NodeId(search_id))
            print(f"  - {search_node.name or '<unnamed>'} ({search_id})")
        return

    # Process searches
    if args.search_id:
        if args.search_id not in all_searches:
            print(f"Error: Search ID '{args.search_id}' not found", file=sys.stderr)
            sys.exit(1)
        print_search_info(store, args.search_id)
    elif args.all:
        print(f"Processing {len(all_searches)} search nodes...")
        for search_id in all_searches:
            print_search_info(store, search_id)
            print("-" * 60)
    else:
        print("Please specify --search-id, --all, or --list")
        sys.exit(1)


if __name__ == "__main__":
    main()

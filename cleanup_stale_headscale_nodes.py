#!/usr/bin/env python3
"""
Script to clean up stale Headscale nodes (controlplane* and worker* nodes).

This script:
1. Lists all nodes using headscale CLI
2. Filters for controlplane* and worker* nodes
3. Shows their status and last seen time
4. Optionally deletes selected nodes with confirmation

Usage:
    python3 cleanup_stale_headscale_nodes.py [--dry-run] [--force] [--all-offline]
"""

import argparse
from datetime import UTC, datetime
import json
import subprocess
from typing import Any


def run_headscale_command(args: list[str]) -> dict[str, Any]:
    """Run a headscale command and return JSON output."""
    cmd = ["headscale", *args]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    if args[-1] == "json":
        return json.loads(result.stdout)
    return {"output": result.stdout}


def get_all_nodes() -> list[dict[str, Any]]:
    """Get all nodes from headscale."""
    return run_headscale_command(["nodes", "list", "-o", "json"])


def filter_stale_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter nodes to only include controlplane* and worker* nodes."""
    stale_nodes = []
    for node in nodes:
        name = node.get("name", "")
        if name.startswith(("controlplane", "worker")):
            stale_nodes.append(node)
    return stale_nodes


def format_last_seen(last_seen_data: dict[str, Any]) -> str:
    """Format last seen timestamp for display."""
    if not last_seen_data:
        return "Never"

    # Extract seconds and nanos from the timestamp
    seconds = last_seen_data.get("seconds", 0)
    if seconds == 0:
        return "Never"

    # Convert to datetime
    last_seen = datetime.fromtimestamp(seconds, tz=UTC)
    now = datetime.now(UTC)

    # Calculate time difference
    diff = now - last_seen
    days = diff.days
    hours, remainder = divmod(diff.seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    if days > 0:
        return f"{days}d {hours}h ago"
    if hours > 0:
        return f"{hours}h {minutes}m ago"
    return f"{minutes}m ago"


def is_node_offline(node: dict[str, Any]) -> bool:
    """Check if a node appears to be offline based on last_seen."""
    last_seen = node.get("last_seen", {})
    if not last_seen:
        return True

    seconds = last_seen.get("seconds", 0)
    if seconds == 0:
        return True

    # Consider offline if not seen in last hour
    now = datetime.now(UTC).timestamp()
    return (now - seconds) > 3600  # 1 hour


def display_nodes(nodes: list[dict[str, Any]]) -> None:
    """Display nodes in a formatted table."""
    if not nodes:
        print("No controlplane or worker nodes found.")
        return

    print(f"{'ID':<4} {'Name':<25} {'IP Address':<15} {'Status':<8} {'Last Seen'}")
    print("-" * 80)

    for node in nodes:
        node_id = node.get("id", "?")
        name = node.get("name", "unknown")
        ip_addresses = node.get("ip_addresses", [])
        ip_addr = ip_addresses[0] if ip_addresses else "none"

        # Determine status
        status = "OFFLINE" if is_node_offline(node) else "online"

        last_seen = format_last_seen(node.get("last_seen", {}))

        print(f"{node_id:<4} {name:<25} {ip_addr:<15} {status:<8} {last_seen}")


def select_nodes_for_deletion(nodes: list[dict[str, Any]], all_offline: bool = False) -> list[int]:
    """Let user select which nodes to delete."""
    offline_nodes = [node for node in nodes if is_node_offline(node)]

    if not offline_nodes:
        print("\nNo offline nodes found to delete.")
        return []

    if all_offline:
        # Select all offline nodes automatically
        print(f"\nAuto-selecting all {len(offline_nodes)} offline nodes for deletion.")
        return [node["id"] for node in offline_nodes]

    print(f"\nFound {len(offline_nodes)} offline nodes:")
    display_nodes(offline_nodes)

    while True:
        response = input(f"\nDelete all {len(offline_nodes)} offline nodes? (y/n/list): ").lower().strip()
        if response in {"y", "yes"}:
            return [node["id"] for node in offline_nodes]
        if response in {"n", "no"}:
            return []
        if response == "list":
            display_nodes(offline_nodes)
        else:
            print("Please enter 'y', 'n', or 'list'")


def delete_nodes(node_ids: list[int], dry_run: bool = False, force: bool = False) -> None:
    """Delete the specified nodes."""
    if not node_ids:
        print("No nodes to delete.")
        return

    if dry_run:
        print(f"\n[DRY RUN] Would delete {len(node_ids)} nodes with IDs: {', '.join(map(str, node_ids))}")
        return

    if not force:
        print(f"\nAbout to delete {len(node_ids)} nodes with IDs: {', '.join(map(str, node_ids))}")
        confirm = input("Are you absolutely sure? Type 'DELETE' to confirm: ")
        if confirm != "DELETE":
            print("Deletion cancelled.")
            return

    print(f"\nDeleting {len(node_ids)} nodes...")

    deleted_count = 0
    failed_count = 0

    for i, node_id in enumerate(node_ids, 1):
        # Show progress
        progress_percent = (i / len(node_ids)) * 100
        print(f"[{i:>3}/{len(node_ids):>3}] ({progress_percent:5.1f}%) Deleting node {node_id}... ", end="", flush=True)

        run_headscale_command(["nodes", "delete", "-i", str(node_id), "--force"])
        print("✓")
        deleted_count += 1

    print(f"\nDeletion complete: {deleted_count} deleted, {failed_count} failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without actually deleting")
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompts")
    parser.add_argument(
        "--all-offline", action="store_true", help="Automatically select all offline nodes for deletion"
    )

    args = parser.parse_args()

    print("Fetching nodes from Headscale...")
    all_nodes = get_all_nodes()
    stale_nodes = filter_stale_nodes(all_nodes)

    if not stale_nodes:
        print("No controlplane or worker nodes found.")
        return

    print(f"\nFound {len(stale_nodes)} controlplane/worker nodes:")
    display_nodes(stale_nodes)

    # Select nodes for deletion
    nodes_to_delete = select_nodes_for_deletion(stale_nodes, args.all_offline)

    if nodes_to_delete:
        delete_nodes(nodes_to_delete, args.dry_run, args.force)
        print(f"\nOperation completed. Deleted {len(nodes_to_delete)} nodes.")
    else:
        print("\nNo nodes selected for deletion.")


if __name__ == "__main__":
    main()

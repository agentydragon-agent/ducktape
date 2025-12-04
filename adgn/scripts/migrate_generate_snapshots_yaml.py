#!/usr/bin/env python3
"""
Migration script for Phase 3.1: Generate consolidated snapshots.yaml

This script:
1. Walks all directories under specimens/ looking for manifest.yaml files
2. For each manifest:
   - Derives slug from directory path (e.g., ducktape/2025-11-26-00)
   - Extracts source, split, bundle fields
3. Consolidates all into a single specimens/snapshots.yaml file
4. Prints summary statistics

Usage:
    python scripts/migrate_generate_snapshots_yaml.py
"""

import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


def main() -> None:
    # Find the specimens directory
    script_dir = Path(__file__).parent
    adgn_root = script_dir.parent
    specimens_dir = adgn_root / "src" / "adgn" / "props" / "specimens"

    if not specimens_dir.exists():
        print(f"Error: specimens directory not found at {specimens_dir}", file=sys.stderr)
        sys.exit(1)

    # Find all manifest.yaml files
    manifest_files = sorted(specimens_dir.rglob("manifest.yaml"))

    if not manifest_files:
        print(f"Warning: no manifest.yaml files found in {specimens_dir}", file=sys.stderr)
        sys.exit(0)

    print(f"Found {len(manifest_files)} manifest files")

    # Collect all snapshots
    snapshots: dict[str, Any] = {}
    split_counts = Counter()

    for manifest_path in manifest_files:
        # Derive slug from path relative to specimens/
        # E.g., specimens/ducktape/2025-11-26-00/manifest.yaml -> ducktape/2025-11-26-00
        relative_path = manifest_path.parent.relative_to(specimens_dir)
        slug = str(relative_path)

        # Read manifest
        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)

        if not manifest:
            print(f"Warning: empty manifest at {manifest_path}", file=sys.stderr)
            continue

        # Extract fields
        source = manifest.get("source")
        split = manifest.get("split")
        bundle = manifest.get("bundle")

        if not source:
            print(f"Warning: no source field in {manifest_path}", file=sys.stderr)
            continue

        if not split:
            print(f"Warning: no split field in {manifest_path}", file=sys.stderr)
            continue

        # Build snapshot entry
        snapshot_entry: dict[str, Any] = {
            "source": source,
            "split": split,
        }

        # Add bundle field (preserving null vs absent distinction)
        if "bundle" in manifest:
            snapshot_entry["bundle"] = bundle

        snapshots[slug] = snapshot_entry
        split_counts[split] += 1

        print(f"  {slug}: split={split}")

    # Write snapshots.yaml
    output_path = specimens_dir / "snapshots.yaml"

    # Use custom YAML dumper for clean formatting
    yaml.SafeDumper.add_representer(
        type(None),
        lambda dumper, value: dumper.represent_scalar('tag:yaml.org,2002:null', 'null')
    )

    with open(output_path, "w") as f:
        yaml.dump(
            snapshots,
            f,
            Dumper=yaml.SafeDumper,
            default_flow_style=False,
            sort_keys=False,  # Preserve insertion order
            allow_unicode=True,
        )

    print(f"\n✓ Wrote {output_path}")
    print(f"\nSummary:")
    print(f"  Total snapshots: {len(snapshots)}")
    print(f"  By split:")
    for split, count in sorted(split_counts.items()):
        print(f"    {split}: {count}")


if __name__ == "__main__":
    main()

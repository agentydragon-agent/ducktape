#!/usr/bin/env python3
"""Command-line tool for managing metadata versions."""

import argparse
import json
import sys
from pathlib import Path

from ducktape_llm_common import METADATA_VERSION
from ducktape_llm_common.utils import (
    IncompatibleVersionError,
    ensure_version_file,
    find_version_files,
    get_metadata_version,
    get_version_info,
    get_version_report,
    validate_version_strict,
)


def cmd_check(args):
    """Check the metadata version of a path."""
    path = Path(args.path)
    version = get_metadata_version(path)

    if args.quiet:
        print(version)
    else:
        print(f"Metadata version at {path}: {version}")

        # Show version info if available
        info = get_version_info(version)
        if info:
            print(f"Description: {info.description}")
            print(f"Introduced: {info.introduced}")

    # If expecting specific version, validate it
    if args.expect:
        try:
            validate_version_strict(path, expected_version=args.expect)
            if not args.quiet:
                print(f"✓ Version {version} matches expected {args.expect}")
            return 0
        except IncompatibleVersionError:
            if not args.quiet:
                print(f"✗ Version {version} does not match expected {args.expect}")
            return 1

    return 0


def cmd_init(args):
    """Initialize a .metadata-version file."""
    path = Path(args.path)
    version = args.version or METADATA_VERSION

    if path.exists() and not path.is_dir():
        print(f"Error: {path} is not a directory", file=sys.stderr)
        return 1

    if not path.exists():
        if args.create_dir:
            path.mkdir(parents=True)
            print(f"Created directory: {path}")
        else:
            print(f"Error: Directory {path} does not exist", file=sys.stderr)
            return 1

    was_created = ensure_version_file(path, version=version, force=args.force)

    if was_created:
        print(f"Created .metadata-version file with version {version}")
    else:
        print(
            f".metadata-version file already exists with version {get_metadata_version(path)}"
        )
        if not args.force:
            print("Use --force to overwrite")

    return 0


def cmd_find(args):
    """Find all .metadata-version files in a directory tree."""
    root = Path(args.root)

    if not root.exists():
        print(f"Error: Directory {root} does not exist", file=sys.stderr)
        return 1

    version_files = find_version_files(root)

    if not version_files:
        print("No .metadata-version files found")
        return 0

    if args.json:
        # JSON output
        data = [
            {
                "path": str(path),
                "version": version,
                "relative_path": str(path.relative_to(root)),
            }
            for path, version in version_files
        ]
        print(json.dumps(data, indent=2))
    else:
        # Human-readable output
        print(f"Found {len(version_files)} version files:")

        # Group by version
        by_version = {}
        for path, version in version_files:
            by_version.setdefault(version, []).append(path)

        for version in sorted(by_version.keys()):
            paths = by_version[version]
            print(f"\nVersion {version} ({len(paths)} locations):")
            for path in sorted(paths):
                relative = path.relative_to(root)
                print(f"  {relative}")

    return 0


def cmd_report(args):
    """Generate a version report for a directory tree."""
    root = Path(args.root)

    if not root.exists():
        print(f"Error: Directory {root} does not exist", file=sys.stderr)
        return 1

    report = get_version_report(root)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Version Report for {root}")
        print("=" * 50)
        print(f"Current package version: {report['current_version']}")
        print(f"Total versioned paths: {report['total_versioned_paths']}")

        if report["version_distribution"]:
            print("\nVersion distribution:")
            for version, count in sorted(report["version_distribution"].items()):
                info = get_version_info(version)
                desc = f" ({info.description})" if info else ""
                print(f"  Version {version}: {count} locations{desc}")

        if report["incompatible_paths"]:
            print(f"\n⚠️  Found {len(report['incompatible_paths'])} incompatible paths:")
            for item in report["incompatible_paths"]:
                path = Path(item["path"]).relative_to(root)
                print(f"  {path}: v{item['version']} - {item['reason']}")
            return 1
        else:
            print("\n✓ All paths are compatible with current version")

    return 0


def cmd_info(args):
    """Show information about a specific version."""
    version = args.version
    info = get_version_info(version)

    if not info:
        print(f"No information available for version {version}", file=sys.stderr)
        return 1

    if args.json:
        data = {
            "version": info.version,
            "description": info.description,
            "introduced": info.introduced,
            "changes": info.changes,
            "compatible_with": info.compatible_with,
        }
        print(json.dumps(data, indent=2))
    else:
        print(f"Version {info.version}")
        print("=" * 40)
        print(f"Description: {info.description}")
        print(f"Introduced: {info.introduced}")
        print("\nChanges:")
        for change in info.changes:
            print(f"  - {change}")

        if info.compatible_with:
            print(
                f"\nCompatible with versions: {', '.join(map(str, info.compatible_with))}"
            )

    return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Manage metadata versions for ducktape-llm-common"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # check command
    check_parser = subparsers.add_parser("check", help="Check metadata version")
    check_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to check (default: current directory)",
    )
    check_parser.add_argument(
        "-e", "--expect", type=int, help="Expected version (exit 1 if different)"
    )
    check_parser.add_argument(
        "-q", "--quiet", action="store_true", help="Quiet output (version number only)"
    )

    # init command
    init_parser = subparsers.add_parser(
        "init", help="Initialize .metadata-version file"
    )
    init_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to initialize (default: current directory)",
    )
    init_parser.add_argument(
        "-v",
        "--version",
        type=int,
        help=f"Version to use (default: {METADATA_VERSION})",
    )
    init_parser.add_argument(
        "-f", "--force", action="store_true", help="Overwrite existing file"
    )
    init_parser.add_argument(
        "-c",
        "--create-dir",
        action="store_true",
        help="Create directory if it doesn't exist",
    )

    # find command
    find_parser = subparsers.add_parser(
        "find", help="Find all version files in directory tree"
    )
    find_parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Root directory to search (default: current directory)",
    )
    find_parser.add_argument("-j", "--json", action="store_true", help="Output as JSON")

    # report command
    report_parser = subparsers.add_parser("report", help="Generate version report")
    report_parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Root directory to analyze (default: current directory)",
    )
    report_parser.add_argument(
        "-j", "--json", action="store_true", help="Output as JSON"
    )

    # info command
    info_parser = subparsers.add_parser("info", help="Show information about a version")
    info_parser.add_argument("version", type=int, help="Version number")
    info_parser.add_argument("-j", "--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Dispatch to command handler
    handlers = {
        "check": cmd_check,
        "init": cmd_init,
        "find": cmd_find,
        "report": cmd_report,
        "info": cmd_info,
    }

    handler = handlers.get(args.command)
    if handler:
        return handler(args)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

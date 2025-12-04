#!/usr/bin/env python3
"""
Migrate issue files from old helpers to new helpers (Phase 3.2).

Auto-migrates simple cases (~372 files using issueOneOccurrence).
Flags files needing manual review (~33 files using issueWithOccurrences/issueOccurrencesFromLines).

Usage:
    python scripts/migrate_issue_files.py --dry-run  # Preview changes
    python scripts/migrate_issue_files.py            # Execute migration
"""

import argparse
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass
class MigrationResult:
    """Result of migrating a single file."""

    source_path: Path
    dest_path: Path
    old_helper: str
    new_helper: str
    snapshot_slug: str
    action: Literal["auto_migrated", "needs_manual_review"]
    reason: str | None = None


@dataclass
class MigrationStats:
    """Statistics for the entire migration."""

    auto_migrated: list[MigrationResult]
    needs_manual_review: list[MigrationResult]

    @property
    def total_auto(self) -> int:
        return len(self.auto_migrated)

    @property
    def total_manual(self) -> int:
        return len(self.needs_manual_review)

    @property
    def total(self) -> int:
        return self.total_auto + self.total_manual


def extract_snapshot_slug(file_path: Path) -> str:
    """
    Extract snapshot slug from file path.

    Examples:
        specimens/ducktape/2025-11-26-00/issues/dead-code.libsonnet
        → ducktape/2025-11-26-00

        specimens/crush/2025-08-30-internal_db/false_positives/fp-002.libsonnet
        → crush/2025-08-30-internal_db
    """
    parts = file_path.parts
    specimens_idx = parts.index("specimens")
    repo = parts[specimens_idx + 1]
    version = parts[specimens_idx + 2]
    return f"{repo}/{version}"


def detect_helper_type(content: str) -> tuple[str | None, bool]:
    """
    Detect which helper is used and whether it's in issues/ or false_positives/.

    Returns:
        (helper_name, is_false_positive)
        helper_name is None if no recognized helper found
    """
    if "I.issueOneOccurrence" in content:
        # Check for should_flag parameter
        is_fp = "should_flag=false" in content or "should_flag = false" in content
        return ("issueOneOccurrence", is_fp)
    elif "I.issueWithOccurrences" in content:
        return ("issueWithOccurrences", False)
    elif "I.issueOccurrencesFromLines" in content:
        return ("issueOccurrencesFromLines", False)
    return (None, False)


def transform_issue_one_occurrence(
    content: str, snapshot_slug: str, is_false_positive: bool
) -> str:
    """
    Transform issueOneOccurrence to issue() or falsePositive().

    Changes:
    1. Replace helper name
    2. Add snapshot parameter as first argument
    3. Remove should_flag parameter (for FPs)
    4. Update import path ../../lib.libsonnet -> ../lib.libsonnet
    """
    new_helper = "falsePositive" if is_false_positive else "issue"

    # Update import path (one fewer ..)
    content = content.replace(
        "local I = import '../../specimens/lib.libsonnet';",
        "local I = import '../lib.libsonnet';",
    )

    # Remove should_flag parameter for false positives
    if is_false_positive:
        # Remove should_flag=false line (with optional whitespace and comma)
        content = re.sub(
            r"\s*should_flag\s*=\s*false\s*,?\s*\n", "\n", content, flags=re.MULTILINE
        )

    # Replace helper call and add snapshot parameter
    # Match: I.issueOneOccurrence(
    # Replace with: I.{new_helper}(\n  snapshot='{slug}',
    pattern = r"I\.issueOneOccurrence\(\s*"
    replacement = f"I.{new_helper}(\n  snapshot='{snapshot_slug}',\n  "
    content = re.sub(pattern, replacement, content)

    return content


def get_dest_path(source_path: Path) -> Path:
    """
    Calculate destination path for migrated file.

    Move from specimens/{slug}/issues/*.libsonnet
    or specimens/{slug}/false_positives/*.libsonnet
    to specimens/{slug}/*.libsonnet
    """
    parts = list(source_path.parts)
    specimens_idx = parts.index("specimens")

    # Remove 'issues' or 'false_positives' directory from path
    if parts[specimens_idx + 3] in ("issues", "false_positives"):
        # specimens/repo/version/issues/file.libsonnet
        # -> specimens/repo/version/file.libsonnet
        dest_parts = parts[: specimens_idx + 3] + parts[specimens_idx + 4 :]
        return Path(*dest_parts)

    # Already flat (shouldn't happen during migration)
    return source_path


def migrate_file(
    source_path: Path, dry_run: bool = False
) -> MigrationResult | None:
    """
    Migrate a single issue file.

    Returns:
        MigrationResult if file was processed
        None if file should be skipped
    """
    content = source_path.read_text()
    snapshot_slug = extract_snapshot_slug(source_path)

    helper, is_fp = detect_helper_type(content)

    if helper is None:
        # No recognized helper (maybe already migrated?)
        return None

    # Check if manual review needed
    if helper in ("issueWithOccurrences", "issueOccurrencesFromLines"):
        reason = (
            "Needs issueMulti with notes + expect_caught_from"
            if helper == "issueWithOccurrences"
            else "Needs expansion to explicit occurrences"
        )
        return MigrationResult(
            source_path=source_path,
            dest_path=get_dest_path(source_path),
            old_helper=helper,
            new_helper="issueMulti",
            snapshot_slug=snapshot_slug,
            action="needs_manual_review",
            reason=reason,
        )

    # Auto-migrate issueOneOccurrence
    new_helper = "falsePositive" if is_fp else "issue"
    new_content = transform_issue_one_occurrence(content, snapshot_slug, is_fp)
    dest_path = get_dest_path(source_path)

    if not dry_run:
        # Create destination directory if needed
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # Write transformed content
        dest_path.write_text(new_content)

        # Remove source file if different from dest
        if source_path != dest_path:
            source_path.unlink()

    return MigrationResult(
        source_path=source_path,
        dest_path=dest_path,
        old_helper=helper,
        new_helper=new_helper,
        snapshot_slug=snapshot_slug,
        action="auto_migrated",
    )


def find_all_issue_files(specimens_dir: Path) -> list[Path]:
    """Find all .libsonnet files in issues/ and false_positives/ directories."""
    files = []
    for pattern in ("*/issues/*.libsonnet", "*/false_positives/*.libsonnet"):
        files.extend(specimens_dir.glob(f"*/{pattern}"))
    return sorted(files)


def print_report(stats: MigrationStats, dry_run: bool, show_samples: bool = False) -> None:
    """Print migration report."""
    mode = "DRY RUN" if dry_run else "EXECUTED"

    print(f"\n{'='*80}")
    print(f"MIGRATION REPORT ({mode})")
    print(f"{'='*80}\n")

    print(f"Total files processed: {stats.total}")
    print(f"  - Auto-migrated: {stats.total_auto}")
    print(f"  - Need manual review: {stats.total_manual}")

    if stats.auto_migrated:
        print(f"\n{'-'*80}")
        print(f"AUTO-MIGRATED FILES ({stats.total_auto})")
        print(f"{'-'*80}")

        by_helper = {}
        for result in stats.auto_migrated:
            key = f"{result.old_helper} → {result.new_helper}"
            by_helper.setdefault(key, []).append(result)

        for helper_transform, results in sorted(by_helper.items()):
            print(f"\n{helper_transform} ({len(results)} files):")
            for r in results[:5]:  # Show first 5 examples
                print(f"  {r.source_path}")
                if r.source_path != r.dest_path:
                    print(f"    → {r.dest_path}")
            if len(results) > 5:
                print(f"  ... and {len(results) - 5} more")

    if stats.needs_manual_review:
        print(f"\n{'-'*80}")
        print(f"FILES NEEDING MANUAL REVIEW ({stats.total_manual})")
        print(f"{'-'*80}\n")

        by_helper = {}
        for result in stats.needs_manual_review:
            by_helper.setdefault(result.old_helper, []).append(result)

        for helper, results in sorted(by_helper.items()):
            print(f"\n{helper} ({len(results)} files):")
            print(f"Action needed: {results[0].reason}\n")
            for r in results:
                print(f"  {r.source_path}")

        print(f"\n{'-'*80}")
        print("MANUAL MIGRATION GUIDE")
        print(f"{'-'*80}\n")

        print("For issueWithOccurrences → issueMulti:")
        print("  1. Change helper from I.issueWithOccurrences to I.issueMulti")
        print("  2. Add snapshot='<slug>' as first parameter")
        print("  3. Add 'note' field to ALL occurrences (required)")
        print("  4. Add 'expect_caught_from' field to ALL occurrences if total files > 1")
        print("     - Format: [['file1.py'], ['file2.py', 'file3.py']]")
        print("     - Semantics: Issue detectable from ANY of these file sets (OR)")
        print("  5. Update import path: ../../lib.libsonnet → ../lib.libsonnet")
        print("  6. Move file from issues/ to parent directory")
        print()
        print("For issueOccurrencesFromLines → issueMulti:")
        print("  1. Change helper from I.issueOccurrencesFromLines to I.issueMulti")
        print("  2. Expand linesByFile to explicit occurrence objects")
        print("  3. Each occurrence needs: files={...}, note='...', expect_caught_from=[...]")
        print("  4. Add snapshot parameter and update import/move file as above")
        print()

    print(f"\n{'='*80}\n")


def cleanup_empty_directories(specimens_dir: Path, dry_run: bool) -> None:
    """Remove empty issues/ and false_positives/ directories after migration."""
    count = 0
    for dir_name in ("issues", "false_positives"):
        for dir_path in specimens_dir.glob(f"*/*/{dir_name}"):
            if dir_path.is_dir() and not any(dir_path.iterdir()):
                if not dry_run:
                    dir_path.rmdir()
                count += 1

    if count > 0:
        action = "Would remove" if dry_run else "Removed"
        print(f"\n{action} {count} empty directories")


def validate_environment(specimens_dir: Path) -> bool:
    """Validate that the environment is ready for migration."""
    lib_path = specimens_dir / "lib.libsonnet"
    if not lib_path.exists():
        print(f"Error: lib.libsonnet not found at {lib_path}")
        return False

    # Check that new helpers exist in lib.libsonnet
    lib_content = lib_path.read_text()
    required_helpers = ["issue:", "issueMulti:", "falsePositive:", "falsePositiveMulti:"]
    missing = [h for h in required_helpers if h not in lib_content]

    if missing:
        print(f"Error: lib.libsonnet is missing new helpers: {', '.join(missing)}")
        print("Please ensure Phase 2 (Jsonnet helper redesign) is complete before running migration.")
        return False

    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying files",
    )
    parser.add_argument(
        "--specimens-dir",
        type=Path,
        default=Path("src/adgn/props/specimens"),
        help="Path to specimens directory (default: src/adgn/props/specimens)",
    )
    args = parser.parse_args()

    specimens_dir = args.specimens_dir
    if not specimens_dir.exists():
        print(f"Error: Specimens directory not found: {specimens_dir}")
        return

    if not validate_environment(specimens_dir):
        return

    print(f"Finding issue files in {specimens_dir}...")
    files = find_all_issue_files(specimens_dir)
    print(f"Found {len(files)} files to process")

    stats = MigrationStats(auto_migrated=[], needs_manual_review=[])

    for file_path in files:
        result = migrate_file(file_path, dry_run=args.dry_run)
        if result is None:
            continue

        if result.action == "auto_migrated":
            stats.auto_migrated.append(result)
        else:
            stats.needs_manual_review.append(result)

    print_report(stats, dry_run=args.dry_run, show_samples=args.dry_run)

    # Cleanup empty directories
    cleanup_empty_directories(specimens_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

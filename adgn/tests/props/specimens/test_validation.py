from __future__ import annotations

from pathlib import Path
import re

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from adgn.props.db import get_session
from adgn.props.db.models import Snapshot
from adgn.props.db.sync import sync_snapshots_to_db, sync_issues_to_db, sync_critic_scopes_to_db
from adgn.props.db.sync import get_specimens_base_path
from adgn.props.ids import SnapshotSlug
from adgn.props.models.snapshot import LocalSource
from adgn.props.hydration import SnapshotHydrator


@pytest.fixture
def synced_test_db(test_db):
    """Test database with production specimens synced."""
    specimens_dir = get_specimens_base_path()
    with get_session() as session:
        sync_snapshots_to_db(session, specimens_dir)
        sync_issues_to_db(session, specimens_dir)
        sync_critic_scopes_to_db(session, specimens_dir)
        session.commit()
    return test_db


async def test_specimen_issues_and_false_positives_load(
    production_specimens_hydrator: SnapshotHydrator, synced_test_db
) -> None:
    """Test that all specimen issues and false positives load without errors."""
    # Get all specimens from synced database
    with get_session() as session:
        snapshots = session.query(Snapshot).all()
        specimens = [s.slug for s in snapshots]

    failures = []

    for specimen in specimens:
        # Load both issues/ and false_positives/ via the hydrator; assert no load errors
        try:
            async with production_specimens_hydrator.hydrate(specimen) as _hydrated:
                # If we get here, loading succeeded - no errors
                pass
        except Exception as e:
            # Load failed - format error for display
            error_str = str(e)
            error_msg = [f"Snapshot '{specimen}' has invalid Jsonnet files:", error_str]

            # Try to extract file path and line number for context (best-effort)
            try:
                matches = re.findall(r"(/[^:]+):(\d+):", error_str)
                if matches:
                    path_str, ln_str = matches[-1]
                    ln = int(ln_str)
                    p = Path(path_str)
                    if p.exists():
                        src_lines = p.read_text().splitlines()
                        start = max(1, ln - 3)
                        end = min(len(src_lines), ln + 3)
                        error_msg.append(f"--- context {p}:{ln} ---")
                        for i in range(start, end + 1):
                            error_msg.append(f"{i:>4}: {src_lines[i - 1]}")
            except Exception as ctx_err:
                error_msg.append(f"(Could not extract context: {ctx_err})")

            failures.append("\n".join(error_msg))

    # Report all failures at once
    if failures:
        pytest.fail("\n\n".join(failures))


@pytest.mark.asyncio
async def test_specimen_references_are_valid(
    production_specimens_hydrator: SnapshotHydrator, synced_test_db
) -> None:
    """Validate that all file references and line ranges in issues are valid.

    For each specimen:
    1. Hydrate the specimen to get actual files
    2. For each issue, validate that:
       - All referenced files exist in the hydrated copy
       - All line ranges are within the file's actual line count
    """
    # Get all specimens from synced database
    with get_session() as session:
        snapshots = session.query(Snapshot).all()
        specimens = [s.slug for s in snapshots]

    failures = []

    for specimen in specimens:
        # Load snapshot from database to get manifest and issues
        # Use selectinload to eagerly load relationships to avoid DetachedInstanceError
        with get_session() as session:
            snapshot_db = session.execute(
                select(Snapshot)
                .where(Snapshot.slug == specimen)  # type: ignore[arg-type]
                .options(selectinload(Snapshot.true_positives), selectinload(Snapshot.false_positives))
            ).scalar_one_or_none()

            assert snapshot_db is not None, f"Snapshot {specimen} not found in database"
            manifest = snapshot_db.source

            # Skip validation for local specimens (they don't hydrate the same way)
            if isinstance(manifest, LocalSource):
                continue  # Skip this specimen

            # Use relationships to get issues (now eagerly loaded)
            true_positives_list = snapshot_db.true_positives
            false_positives_list = snapshot_db.false_positives

            # Expunge all instances from session to prevent expiration on commit
            # This keeps the loaded data accessible after the session closes
            session.expunge_all()

        # Hydrate source code
        async with production_specimens_hydrator.hydrate(specimen) as hydrated:
            content_root = hydrated.content_root

            # Collect all file references and their line ranges from issues
            file_references: dict[Path, set[tuple[int, int | None]]] = {}

            # Check true positives
            for issue in true_positives_list:
                for tp_occurrence in issue.occurrences:
                    for file_path, ranges in tp_occurrence.files.items():
                        if file_path not in file_references:
                            file_references[file_path] = set()

                        if ranges:
                            for line_range in ranges:
                                file_references[file_path].add((line_range.start_line, line_range.end_line))

            # Also check false positives
            for fp in false_positives_list:
                for fp_occurrence in fp.occurrences:
                    for file_path, ranges in fp_occurrence.files.items():
                        if file_path not in file_references:
                            file_references[file_path] = set()

                        if ranges:
                            for line_range in ranges:
                                file_references[file_path].add((line_range.start_line, line_range.end_line))

            # If no file references, skip this specimen
            if not file_references:
                continue

            # Validate references using the already-hydrated content root (no double-hydration!)
            errors = []

            for file_path, line_ranges in file_references.items():
                full_path = content_root / file_path

                # Check if file exists
                if not full_path.exists():
                    errors.append(f"File not found in hydrated specimen: {file_path}")
                    continue

                if not full_path.is_file():
                    errors.append(f"Path is not a file: {file_path}")
                    continue

                # Read file and count lines
                try:
                    file_content = full_path.read_text(encoding="utf-8")
                    lines = file_content.splitlines()
                    num_lines = len(lines)

                    # Validate each line range
                    for start_line, end_line in line_ranges:
                        if start_line < 1:
                            errors.append(f"Invalid start_line {start_line} in {file_path} (must be >= 1)")
                        elif start_line > num_lines:
                            errors.append(f"start_line {start_line} exceeds file length {num_lines} in {file_path}")

                        if end_line is not None:
                            if end_line < start_line:
                                errors.append(f"Invalid range [{start_line}, {end_line}] in {file_path} (end < start)")
                            elif end_line > num_lines:
                                errors.append(f"end_line {end_line} exceeds file length {num_lines} in {file_path}")

                except Exception as e:
                    errors.append(f"Error reading {file_path}: {e}")

            if errors:
                error_msg = f"Snapshot '{specimen}' has invalid file references:\n"
                error_msg += "\n".join(f"  - {error}" for error in errors)
                failures.append(error_msg)

    # Report all failures at once
    if failures:
        pytest.fail("\n\n".join(failures))

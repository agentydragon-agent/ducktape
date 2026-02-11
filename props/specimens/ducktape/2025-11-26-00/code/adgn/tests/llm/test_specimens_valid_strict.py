from __future__ import annotations

from pathlib import Path
import re

import pytest
import asyncio

from adgn.props.specimens.registry import SpecimenRegistry, find_specimens_base, list_specimen_names
from adgn.props.models.specimen import LocalSource


def _all_specimens() -> list[str]:
    base = find_specimens_base()
    return list_specimen_names(base)


@pytest.mark.parametrize("specimen", _all_specimens())
def test_specimen_issues_and_false_positives_load(specimen: str) -> None:
    # Load both issues/ and false_positives/ via the registry; assert no load errors
    base = find_specimens_base()
    _rec, errors = SpecimenRegistry.load_lenient(specimen, base=base)
    if errors:
        print(f"Specimen '{specimen}' has invalid Jsonnet files (count={len(errors)}):", flush=True)

        for line in errors:
            print(line, flush=True)
            try:
                matches = re.findall(r"(/[^:]+):(\d+):", line)
                if matches:
                    path_str, ln_str = matches[-1]
                    ln = int(ln_str)
                    p = Path(path_str)
                    if p.exists():
                        src_lines = p.read_text().splitlines()
                        start = max(1, ln - 3)
                        end = min(len(src_lines), ln + 3)
                        print(f"--- context {p}:{ln} ---", flush=True)
                        for i in range(start, end + 1):
                            print(f"{i:>4}: {src_lines[i - 1]}", flush=True)
            except Exception:
                pass
    assert not errors, f"Specimen '{specimen}' has invalid Jsonnet files (count={len(errors)})"


@pytest.mark.parametrize("specimen", _all_specimens())
@pytest.mark.asyncio
async def test_specimen_references_are_valid(specimen: str) -> None:
    """Validate that all file references and line ranges in issues are valid.

    For each specimen:
    1. Hydrate the specimen to get actual files
    2. For each issue, validate that:
       - All referenced files exist in the hydrated copy
       - All line ranges are within the file's actual line count
    """
    base = find_specimens_base()
    rec = SpecimenRegistry.load_strict(specimen, base=base)

    # Skip validation for local specimens (they don't hydrate the same way)
    if isinstance(rec.manifest.source, LocalSource):
        pytest.skip(f"Skipping reference validation for local specimen '{specimen}'")

    # Collect all file references and their line ranges from issues
    file_references: dict[str, set[tuple[int, int | None]]] = {}

    for issue in rec.issues.values():
        for occurrence in issue.instances:
            for file_path, ranges in occurrence.files.items():
                if file_path not in file_references:
                    file_references[file_path] = set()

                if ranges:
                    for line_range in ranges:
                        file_references[file_path].add((line_range.start_line, line_range.end_line))

    # Also check false positives
    for fp in rec.false_positives.values():
        for occurrence in fp.instances:
            for file_path, ranges in occurrence.files.items():
                if file_path not in file_references:
                    file_references[file_path] = set()

                if ranges:
                    for line_range in ranges:
                        file_references[file_path].add((line_range.start_line, line_range.end_line))

    # If no file references, skip validation
    if not file_references:
        pytest.skip(f"Specimen '{specimen}' has no file references to validate")

    # Hydrate the specimen and validate references
    async with rec.hydrated_copy() as content_root:
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
                        errors.append(
                            f"Invalid start_line {start_line} in {file_path} (must be >= 1)"
                        )
                    elif start_line > num_lines:
                        errors.append(
                            f"start_line {start_line} exceeds file length {num_lines} in {file_path}"
                        )

                    if end_line is not None:
                        if end_line < start_line:
                            errors.append(
                                f"Invalid range [{start_line}, {end_line}] in {file_path} (end < start)"
                            )
                        elif end_line > num_lines:
                            errors.append(
                                f"end_line {end_line} exceeds file length {num_lines} in {file_path}"
                            )

            except Exception as e:
                errors.append(f"Error reading {file_path}: {e}")

        if errors:
            error_msg = f"Specimen '{specimen}' has invalid file references:\n"
            error_msg += "\n".join(f"  - {error}" for error in errors)
            pytest.fail(error_msg)

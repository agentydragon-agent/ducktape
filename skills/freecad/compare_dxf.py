"""Compare DXF files, stripping non-deterministic header fields."""

import difflib
import re
from pathlib import Path

# DXF group code 999 = comment. The next line after 999 is the comment value.
# FreeCAD writes version info here which varies across installs.
_STRIP_PATTERNS = re.compile(r"^\$TD(CREATE|UPDATE)|^\$VERSIONSTRING$")


def normalize_dxf(text: str) -> list[str]:
    """Strip non-deterministic lines from DXF text."""
    lines = text.splitlines(keepends=True)
    result = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\n")
        # Group code 999 = comment: skip this line and the next (value)
        if line.strip() == "999":
            i += 2  # skip group code + value
            continue
        # Header variables that change between versions/runs
        if _STRIP_PATTERNS.match(line.strip()):
            i += 2  # skip variable name + value
            continue
        result.append(lines[i])
        i += 1
    return result


def compare_dxf_files(actual_path: Path, golden_path: Path) -> str | None:
    """Compare two DXF files after normalization. Returns None if match, diff string if mismatch."""
    actual = normalize_dxf(actual_path.read_text())
    golden = normalize_dxf(golden_path.read_text())
    if actual == golden:
        return None
    return "".join(difflib.unified_diff(golden, actual, fromfile="golden", tofile="actual", n=3))

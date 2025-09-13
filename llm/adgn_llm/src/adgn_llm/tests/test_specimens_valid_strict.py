from __future__ import annotations

from typing import List

import pytest

from adgn_llm.properties.specimens.registry import find_specimens_base, list_specimen_names, _jsonnet_load_issues_dir
from adgn_llm.properties.models.issue import SpecimenIssuesLoadError


def _all_specimens() -> List[str]:
    base = find_specimens_base()
    return list_specimen_names(base)


@pytest.mark.parametrize("specimen", _all_specimens())
def test_specimen_issues_are_valid_strict(specimen: str) -> None:
    # Use the single production loader (strict)
    base = find_specimens_base()
    spec_dir = base / specimen
    try:
        _ = _jsonnet_load_issues_dir(spec_dir, strict=True)
    except SpecimenIssuesLoadError as e:
        # Echo a concise header + all collected errors to help debug quickly in CI output
        print(f"Specimen '{specimen}' has invalid issue files (count={len(e.errors)}):", flush=True)
        # Jsonnet (_jsonnet) does not expose structured diagnostics via Python;
        # errors are human-formatted strings. We parse file:line:col from the message
        # to print helpful context for debugging in CI.
        import re
        from pathlib import Path

        for line in e.errors:
            print(line, flush=True)
            # Attempt to extract file:line and print context
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
        # Re-raise to mark this specimen as failing
        raise

from __future__ import annotations

from pathlib import Path
import re

import pytest

from adgn.props.specimens.registry import SpecimenRegistry, find_specimens_base, list_specimen_names


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

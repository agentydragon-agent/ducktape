from __future__ import annotations

from pathlib import Path

import pytest

# Ensure detectors register themselves via module imports
import adgn.props.detectors.__main__  # noqa: F401
from adgn.props.detectors.registry import run_all
from tests.detectors.fixture_utils import copy_fixture

BAD_CASES: list[tuple[str, str, str]] = [
    ("imports_inside_def.py", "imports_inside_def", "python/imports-top"),
    ("inside_import_non_cycle", "imports_inside_def", "python/imports-top"),
    ("dynamic_attr_probe_getattr.py", "dynamic_attr_probe", "python/forbid-dynamic-attrs"),
    ("pathlike_str_casts.py", "pathlike_str_casts", "python/pathlike"),
    ("swallow_errors.py", "swallow_errors", "python/no-swallowing-errors"),
    ("broad_except_order.py", "broad_except_order", "python/scoped-try-except"),
    ("pydantic_v1_config.py", "pydantic_v1_shims", "python/pydantic-2"),
    ("walrus_immediate.py", "walrus_suggest", "python/walrus"),
    ("walrus_ok_reuse.py", "walrus_suggest", "python/walrus"),
    ("tuple_magic_indices.py", "magic_tuple_indices", "avoid-magic-tuple-indices"),
    ("trivial_alias_once.py", "trivial_alias", "no-oneoff-vars-and-trivial-wrappers"),
    ("import_alias_simple.py", "import_aliasing", "no-random-renames"),
    ("from_import_alias_simple.py", "import_aliasing", "no-random-renames"),
    ("nested_if_simple.py", "flatten_nested_guards", "minimize-nesting"),
    ("optional_str_none_or_empty.py", "optional_string_simplify", "boolean-idioms"),
]

OK_CASES: list[tuple[str, str]] = [
    ("compliant_imports_inside_def.py", "imports_inside_def"),
    ("inside_import_cycle", "imports_inside_def"),
    ("compliant_dynamic_attr_probe.py", "dynamic_attr_probe"),
    ("compliant_pathlike_str_casts.py", "pathlike_str_casts"),
    ("compliant_swallow_errors.py", "swallow_errors"),
    ("compliant_broad_except_order.py", "broad_except_order"),
    ("compliant_pydantic_v2.py", "pydantic_v1_shims"),
    ("tuple_small_indices.py", "magic_tuple_indices"),
    ("trivial_alias_reuse.py", "trivial_alias"),
    ("import_alias_collision.py", "import_aliasing"),
    ("import_alias_allowed.py", "import_aliasing"),
    ("nested_if_with_orelse.py", "flatten_nested_guards"),
    ("nested_if_complex_test.py", "flatten_nested_guards"),
    ("optional_str_not_confident.py", "optional_string_simplify"),
]


def _run_case(tmp_path: Path, pkg_base: str, fixture_file: str, detector: str):
    root = tmp_path / "repo"
    dest_rel = f"pkg/{fixture_file}"
    copy_fixture(root, pkg_base, fixture_file, dest_rel)
    return run_all(root, detector_names=[detector])


@pytest.mark.parametrize(("fixture_file", "detector", "expected_property"), BAD_CASES)
def test_detectors_bad(tmp_path: Path, fixture_file: str, detector: str, expected_property: str):
    detections = _run_case(tmp_path, "tests.detectors.fixtures.bad", fixture_file, detector)
    assert detections, f"no detections for {detector}"
    assert any(d.property == expected_property for d in detections)


@pytest.mark.parametrize(("fixture_file", "detector"), OK_CASES)
def test_detectors_ok(tmp_path: Path, fixture_file: str, detector: str):
    detections = _run_case(tmp_path, "tests.detectors.fixtures.ok", fixture_file, detector)
    assert not detections, f"unexpected detections for {detector}: {detections}"

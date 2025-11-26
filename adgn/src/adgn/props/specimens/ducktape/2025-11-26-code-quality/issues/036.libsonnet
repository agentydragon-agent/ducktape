local I = import '../../specimens/lib.libsonnet';

// iss-036: Parameterize test_bundle_validation over all bundle files

I.issueOneOccurrence(
  rationale=|||
    The test file `test_bundle_validation.py` currently hardcodes the bundle path:
    `BUNDLE_PATH = Path(...) / "specimens" / "ducktape" / "specimens.bundle"`

    If multiple bundles exist in the future (e.g., for different specimen groups),
    tests should run against all of them.

    **Fix:** Use `pytest.mark.parametrize` to discover and test all bundle files:

    ```python
    def find_all_bundles() -> list[Path]:
        """Find all specimens.bundle files in the specimens directory."""
        specimens_dir = Path(__file__).parent.parent.parent / "src" / "adgn" / "props" / "specimens"
        return list(specimens_dir.rglob("specimens.bundle"))

    @pytest.mark.parametrize("bundle_path", find_all_bundles(), ids=str)
    def test_no_specimens_files_in_bundle_commits(bundle_path: Path) -> None:
        ...
    ```

    Apply to all 4 test functions. This ensures all bundles are validated as the
    codebase scales.
  |||,
  filesToRanges={
    'adgn/tests/props/test_bundle_validation.py': [
      [12, 12],  // Hardcoded BUNDLE_PATH
      [25, 155],  // All 4 test functions should be parameterized
    ],
  },
)

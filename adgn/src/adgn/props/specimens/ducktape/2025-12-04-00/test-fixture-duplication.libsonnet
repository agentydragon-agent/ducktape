local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The test file uses specimen_relative_path_model and mock_specimen_context repeatedly across many tests (lines 56, 59, 63, 88, etc.). These fixtures should be DRY'd up as shared fixtures. Additionally, the pattern of creating a wrapper Model class with a single field (specimen_relative_path_model fixture at conftest.py:38-44) and parsing with context is repeated across tests, suggesting a factory fixture would reduce duplication.
  |||,
  filesToRanges={'adgn/tests/props/test_paths.py': [[56, 228]]},
)

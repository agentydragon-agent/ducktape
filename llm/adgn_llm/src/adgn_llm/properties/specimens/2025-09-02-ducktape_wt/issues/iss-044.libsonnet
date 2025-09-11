local I = import '../../specimen_issues.libsonnet';

// iss-044: Use pytest standard fixtures for cwd and tmp_path
I.issueOccurrencesFromLines(
  id='iss-044',
  rationale='Test suite contains a hand-rolled cwd manager fixture duplicating standard pytest monkeypatch capabilities; use `monkeypatch.chdir(tmp_path)` and friends instead.',
  properties=['pytest-standard-fixtures'],
  linesByFile={
    'wt/tests/conftest.py': [[153, 169, "Hand-rolled cwd manager: manual `os.chdir` context manager instead of `monkeypatch.chdir`"]],
    'wt/tests/e2e/test_path_watcher_integration.py': [[18, 18, "Raw tempfile usage and manual cleanup; prefer `tmp_path` fixture"]],
    'wt/tests/integration/test_shell_integration.py': [[81, 81, "`NamedTemporaryFile` for script creation; prefer `tmp_path`"]],
  },
)

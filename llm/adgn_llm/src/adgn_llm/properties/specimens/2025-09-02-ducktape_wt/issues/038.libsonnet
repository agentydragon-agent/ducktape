local I = import '../../specimens/lib.libsonnet';

// iss-038: Non-None default with non-optional type in test helper
I.issueOccurrencesFromLines(
  rationale='`env: dict = None` uses a non-None default with a non-optional type; annotate as `dict[str, str] | None` (or build a dict where needed) and handle `None` explicitly',
  // properties=['type-hints'],
  linesByFile={
    'wt/tests/integration/test_shell_integration.py': [37],
  },
)

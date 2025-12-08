local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 15-19 define five constants (RUN_TYPE_CRITIC, RUN_TYPE_GRADER, INPUT_JSON, OUTPUT_JSON, EVENTS_JSONL) that are never imported or used anywhere in the codebase. The module's stated purpose is to be "the single source of truth for all runs-related path construction" and its docstring explicitly says "No path tokens ('grader', 'output.json', etc.) should be hardcoded outside this module."

    However, these constants are being unused/ignored and the some strings are hardcoded elsewhere instead:
    - "events.jsonl" hardcoded in cluster_unknowns.py:111, cli_app/shared.py:60, cli_app/main.py:536, lint_issue.py:430

    Either these constants should be used to replace the hardcoded strings, or they should be deleted as dead code. The module's purpose is being violated by not using these centralized constants.
  |||,
  filesToRanges={'adgn/src/adgn/props/runs_context.py': [[15, 19]]},
)

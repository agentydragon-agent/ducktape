local I = import '../../lib.libsonnet';

// Merged: unnecessary-intermediate-vars, intermediate-var-single-use-path, unnecessary-intermediate-boolean, unnecessary-policies-variable
// All describe intermediate variables used only once that should be inlined

I.issue(
  rationale= |||
    Four locations create intermediate variables used only once in the immediately
    following statement: runner.py lines 44-45 assign cmd/env before passing to
    containers.create; cli.py lines 577-578 assign edit_path before write_text;
    cli.py lines 592-594 assign saved boolean before if check; sqlite.py line 246
    assigns policies before list comprehension.

    Problems: One-off variables add cognitive load, provide no semantic value (names
    don't clarify intent), require extra lines to read, unnecessarily widen variable
    scope.

    Inline values directly at their use sites. Benefits: fewer variables to track,
    more concise code, clearer single-use intent, smaller variable scope.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/policy_eval/runner.py': [
      [44, 45],   // cmd and env intermediate vars
    ],
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [577, 578], // edit_path intermediate var
      [592, 594], // saved boolean intermediate var
    ],
    'adgn/src/adgn/agent/persist/sqlite.py': [
      [246, 246], // policies query result intermediate var
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/policy_eval/runner.py'],
    ['adgn/src/adgn/git_commit_ai/cli.py'],
    ['adgn/src/adgn/agent/persist/sqlite.py'],
  ],
)

local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Line 151 assigns database query result to `proposals` variable, which is used exactly once
    in the list comprehension on lines 152-160. Single-use variables add cognitive overhead
    without providing value.

    Inline the query directly into the comprehension: move the `await` expression into the
    `for p in ...` clause. This is valid Python syntax and makes it clearer that the query
    result is only used for the comprehension.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/approval_policy/server.py': [
      [148, 160],  // proposals_list with unnecessary proposals variable
      [151, 151],  // proposals variable assignment
    ],
  },
)

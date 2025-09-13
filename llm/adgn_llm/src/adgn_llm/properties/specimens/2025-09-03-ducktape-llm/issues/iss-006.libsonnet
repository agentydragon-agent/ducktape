local I = import '../../specimen_issues.libsonnet';

// iss-006: Remove useless comments and trivial docstring
I.issueWithOccurrences(
  rationale= |||
    Useless inline comments and trivial docstrings add noise without conveying durable signal.
    Examples here: “Build status string”; “Detect --amend flag”; and a trivial enum docstring. Historical comments like “Factor out task creation to a single place” should be deleted once complete.
  |||,
  properties=['no-useless-docs'],
  occurrences=[
    { files: { 'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[686, 687]] }, note: 'Useless inline comment “Build status string”' },
    { files: { 'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[772, 772]] }, note: 'Useless inline comment “Detect --amend flag”' },
    { files: { 'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[468, 470]] }, note: 'Trivial enum docstring' },
    { files: { 'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[873, 873]] }, note: 'Historical comment should be removed after refactor' },
  ],
)

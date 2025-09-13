local I = import '../../specimen_issues.libsonnet';

// iss-059: Inline one-off log_file when constructing FileHandler
I.issueOneOccurrence(
  rationale= |||
    `log_file = Path(repo.git_dir) / "git_commit_ai.log"` is only used immediately to create a FileHandler;
    inline the expression at the call site to avoid a one-off local and reduce visual noise.
  |||,
  properties=['no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[776,779]],
  },
)

local I = import '../../specimen_issues.libsonnet';

// iss-010: Inline single-use variables and reduce one-off names
I.issueWithOccurrences(
  rationale= |||
    Avoid one-off variables created only to be used once in the next line(s).
    Inline simple expressions when they don't harm readability, and reduce redundant parallel names that just mirror each other.
  |||,
  properties=['no-oneoff-vars-and-trivial-wrappers'],
  occurrences=[
    { files: { 'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[776, 781]] }, note: 'Inline single-use log_file in logging setup (pass Path(...) directly to FileHandler)' },
    { files: { 'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[462, 465]] }, note: 'Inline mtime expression in cache eviction loop (avoid temporary mtime_s)' },
    { files: { 'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[884, 884], [918, 918]] }, note: 'Move single-use commit_msg_path to first use site; avoid early one-off variable' },
    { files: { 'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[906, 922]] }, note: 'Reduce redundant names in editor flow (final_text/content_before); keep a single source variable' },
  ],
)

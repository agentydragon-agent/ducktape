local I = import '../../specimen_issues.libsonnet';

  // iss-006: Keep paths as Path/PathLike for subprocess
  I.issueOneOccurrence(
    id='iss-006',
    rationale= |||
      `_get_copyable_entries` casts `Path` to `str` only to pass it to `subprocess.run`.
      But that method is fine with `Path`s. Remove the unnecessary cast and just keep paths as `Path`s.
    |||,
    properties=['pathlike'],
    filesToRanges={"wt/wt/server/copy_strategies.py": [[12, 15]]},
  )

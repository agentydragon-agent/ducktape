local I = import '../../specimens/lib.libsonnet';

// iss-031: Useless comment about removing from passthru

I.issueOneOccurrence(
  rationale=|||
    Line 484 comment says "Capture -a/--all (staging flag) to remove from passthru".
    This is obvious - when argparse handles a flag, it's automatically removed from
    passthru (unknown args). The comment documents the delta from a previous version,
    not current behavior.

    **Fix:** Delete the comment. argparse behavior is standard and needs no explanation.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      484,  // Useless comment about removing from passthru
    ],
  },
)

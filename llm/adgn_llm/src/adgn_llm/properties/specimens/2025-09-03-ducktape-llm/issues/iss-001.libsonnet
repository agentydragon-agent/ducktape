local I = import '../../specimen_issues.libsonnet';

// iss-001: Flip TTY guard to early bailout
// Rationale: Prefer early bailout to reduce nesting and make the happy path clearer.
// Current code nests the terminal sizing logic under `if sys.stdout.isatty(): ...`.
// Better: bail out when not a TTY, then run the sizing logic at base level.
// Benefits: flatter control flow, easier to read/maintain; consistent with Early Bailout property.
I.issueOneOccurrence(
  rationale= |||
    The TTY guard should use an early bailout to avoid unnecessary nesting.
    Instead of nesting the main logic under `if sys.stdout.isatty(): ...`, invert the condition and return/skip when not a TTY, then run the terminal sizing at the base level.
  |||,
  properties=['early-bailout'],
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[715, 721]],
  },
)

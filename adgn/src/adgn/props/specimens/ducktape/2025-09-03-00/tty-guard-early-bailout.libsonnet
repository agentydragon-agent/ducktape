local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The TTY guard should use an early bailout to avoid unnecessary nesting.
    Instead of nesting the main logic under `if sys.stdout.isatty(): ...`, invert the condition and return/skip when not a TTY, then run the terminal sizing at the base level.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[715, 721]],
  },
)

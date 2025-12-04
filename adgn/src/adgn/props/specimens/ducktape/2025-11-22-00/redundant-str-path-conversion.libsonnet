local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Code calls `str(Path.cwd())` before passing to `pygit2.discover_repository()`
    (cli.py:662, minicodex_backend.py:163), but pygit2's signature accepts
    `str | Path`. The conversion is redundant.

    Problems: unnecessary conversion (Path already accepted), less readable
    (extra call adds noise), type loss, suggests API requires strings when
    it doesn't.

    Fix: pass `Path.cwd()` directly. Simpler, clearer intent, type-safe.

    General principle: when an API accepts `str | Path`, prefer passing Path
    objects. Only convert when API requires exactly `str`, or for string
    operations/logging.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [662, 662],  // str(Path.cwd()) in discover_repository call
    ],
    'adgn/src/adgn/git_commit_ai/minicodex_backend.py': [
      [163, 163],  // str(Path.cwd()) in discover_repository call
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/git_commit_ai/cli.py'],
    ['adgn/src/adgn/git_commit_ai/minicodex_backend.py'],
  ],
)
